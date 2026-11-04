"""Deterministic documentation and Python AST inspection."""
import ast
import os
import re
from pathlib import Path

from .phrases import IMAGECAPTIONING, NOIMAGECAPTIONING, GENERIC_NAMES

MODELS = {'BlipForConditionalGeneration', 'BlipModel', 'GitForCausalLM',
          'VisionEncoderDecoderModel'}
SKIP = {'.git', '__pycache__', '.venv', 'venv', 'env', '.env'}


def phrase_matches(text, phrases):
    """Return nonoverlapping matches and text with matched spans blanked."""
    text = text.lower()
    matches = []
    for phrase in sorted(phrases, key=len, reverse=True):
        start = text.find(phrase)
        while start >= 0:
            matches.append(phrase)
            text = text[:start] + ' ' * len(phrase) + text[start + len(phrase):]
            start = text.find(phrase)
    return matches, text


def prose(text):
    lines = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith('```'):
            fenced = not fenced
            lines.append('')
        else:
            lines.append('' if fenced else line.replace('`', ''))
    return '\n'.join(lines)


def has_evidence(source):
    """Resolve imports and constructions within one AST; never combine files."""
    tree = ast.parse(source)
    nodes = list(ast.walk(tree))
    shadows = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    imports = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module + '.' + alias.name

    def resolved(node):
        if isinstance(node, ast.Name):
            if node.id in shadows:
                return None
            return imports.get(node.id)
        if isinstance(node, ast.Attribute):
            base = resolved(node.value)
            if base:
                return base + '.' + node.attr
        return None

    def constructor(call):
        if not isinstance(call, ast.Call):
            return False
        target = call.func
        if isinstance(target, ast.Attribute) and target.attr == 'from_pretrained':
            target = target.value
        full = resolved(target)
        if not full:
            return False
        name = full.rsplit('.', 1)[-1]
        return full.startswith('transformers.') and name in MODELS and name not in shadows

    instances = set()
    # Resolve assignment aliases to constructed instances, including self.model.
    def key(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = key(node.value)
            return base + '.' + node.attr if base else None
        return None

    for _ in range(len(nodes) + 1):
        before = set(instances)
        for node in nodes:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if constructor(value) or (key(value) is not None and key(value) in instances):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    instances.update(key(t) for t in targets if key(t))
        if before == instances:
            break
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        full = resolved(func)
        if full and full == 'transformers.pipeline' and 'pipeline' not in shadows:
            tasks = list(node.args[:1]) + [kw.value for kw in node.keywords if kw.arg == 'task']
            if any(isinstance(t, ast.Constant) and t.value == 'image-to-text' for t in tasks):
                return True
        if isinstance(func, ast.Attribute):
            if func.attr in GENERIC_NAMES and func.attr not in shadows:
                # A local symbol used as the base also defeats imported routes.
                root = func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if not isinstance(root, ast.Name) or root.id not in shadows:
                    return True
            if func.attr == 'generate' and (constructor(func.value) or key(func.value) in instances):
                return True
        elif isinstance(func, ast.Name) and full:
            name = full.rsplit('.', 1)[-1]
            if name in GENERIC_NAMES and name not in shadows:
                return True
    return False


def audit(repo='.', ignore=()):
    root = Path(repo)
    if not root.is_dir():
        raise OSError('Repository is not a directory: ' + str(root))
    evidence = False
    documents = []
    decisions = []
    for directory, dirs, files in os.walk(root, onerror=lambda error: (_ for _ in ()).throw(error)):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not (base / d / 'pyvenv.cfg').exists()
                         and not any((base / d).relative_to(root).as_posix().startswith(i) for i in ignore))
        for name in sorted(files):
            path = base / name
            rel = path.relative_to(root).as_posix()
            if any(rel.startswith(i) for i in ignore):
                decisions.append(rel + ': ignored')
                continue
            if path.suffix == '.py':
                try:
                    found = has_evidence(path.read_text(encoding='utf-8'))
                    evidence = evidence or found
                    decisions.append(rel + (': evidence' if found else ': no evidence'))
                except (SyntaxError, UnicodeError) as error:
                    raise OSError('Cannot parse ' + rel + ': ' + str(error)) from error
            if (rel == 'README.md' or (path.suffix == '.md' and rel.startswith('docs/'))
                    or (path.suffix in {'.md', '.py'} and 'tests' in path.relative_to(root).parts)):
                documents.append((rel, path.read_text(encoding='utf-8')))
    findings = []
    for rel, text in documents:
        denials, remaining = phrase_matches(prose(text), NOIMAGECAPTIONING)
        claims, _ = phrase_matches(remaining, IMAGECAPTIONING)
        test_only = 'tests' in Path(rel).parts
        decisions.append(rel + ': {} claims, {} denials'.format(len(claims), len(denials)))
        for phrases, condition, rule in [(claims, not evidence, 'documented-image-captioning-claim-false'),
                                          (denials, evidence, 'documented-no-image-captioning-claim-false')]:
            if condition:
                for phrase in phrases:
                    findings.append({'rule': rule, 'verdict': 'MEDIUM' if test_only and rule == 'documented-image-captioning-claim-false' else 'HIGH',
                                     'message': '{}: {!r} contradicts detected evidence ({})'.format(rel, phrase, evidence),
                                     'path': rel, 'phrase': phrase})
    return findings, decisions
