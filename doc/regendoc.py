#!/usr/bin/env python

# XXX temporarily vendored copy of
# https://bitbucket.org/RonnyPfannschmidt/regendoc

import argparse
import subprocess

import py
tw = py.io.TerminalWriter()

parser = argparse.ArgumentParser()
parser.add_argument('--update',
                    default=False,
                    action='store_true',
                    help='refresh the files instead of'
                         ' just reporting the difference')
parser.add_argument('files',
                    nargs='+',
                   help='the files to check/update')


def dedent(line, last_indent):
    if last_indent is not None:
        if line[:last_indent].isspace():
            return last_indent, line[last_indent:]
    stripped = line.lstrip(' ')
    return len(line) - len(stripped), stripped


def blocks(lines):
    result = []
    firstline = None
    last_indent = None
    items = []
    for lineno, line in enumerate(lines):

        indent, rest = dedent(line, last_indent)

        if last_indent is None:
            last_indent = indent

        if firstline is None:
            firstline = lineno

        if indent != last_indent:
            if items[0] == '\n':
                del items[0]
                firstline += 1
            if items and items[-1] == '\n':
                del items[-1]
            result.append((last_indent, firstline, items))
            items = [rest]
            last_indent = indent
            firstline = lineno

        else:
            last_indent = indent
            items.append(rest or '\n')

    else:
        try:
            result.append((indent, firstline, items))
        except UnboundLocalError:
            pass
    return result


def correct_content(content, updates):

    lines = content.splitlines(True)
    for update in reversed(updates):
        line = update['line']
        old_lines = len(update['content'].splitlines())
        indent = ' ' * update['indent']
        new_lines = [indent + _line
                     for _line in update['new_content'].splitlines(1)]
        lines[line + 1:line + old_lines + 1] = new_lines

    return ''.join(lines)


def classify(lines, indent=4, line=None):
    if not lines:
        return {'action': None}
    first = lines[0]
    content = ''.join(lines[1:])

    def at(action, target, cwd=None):
        return {
            'action': action,
            'cwd': cwd,
            'target': target,
            'content': content,
            'indent': indent,
            'line': line,
        }

    if first.startswith('# content of'):
        target = first.strip().split()[-1]
        return at('write', target)
    elif first[0] == '$':
        cmd = first[1:].strip()
        return at('shell', cmd)
    elif ' $ ' in first:
        cwd, target = first.split(' $ ')
        target = target.strip()
        return at('shell', target, cwd)
    elif not indent and any(x.strip() == '.. regendoc:wipe' for x in lines):
        return {'action': 'wipe'}

    return at(None, first)


def actions_of(file):
    lines = file.read().splitlines(True)
    for indent, line, data in blocks(lines):
        mapping = classify(lines=data, indent=indent, line=line)
        if mapping['action']:  # None if no idea
            mapping['file'] = file
            yield mapping


def do_write(tmpdir, action):
    #XXX: insecure
    targetfile = tmpdir.join(action['target'])
    targetfile.ensure()
    targetfile.write(action['content'])

def do_shell(tmpdir, action):
    if action['cwd']:
        cwd = action['file'].dirpath().join(action['cwd'])
    else:
        cwd = tmpdir

    proc = subprocess.Popen(
        action['target'],
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out, err = proc.communicate()
    # XXX join with err?
    if out != action['content']:
        import difflib
        differ = difflib.Differ()
        outl = out.splitlines(True)
        contl = action['content'].splitlines(True)
        result = differ.compare(contl, outl)
        printdiff(result)
        return out

def do_wipe(tmpdir, action):
    print('wiping tmpdir %s'%tmpdir)
    for item in tmpdir.listdir():
        item.remove()

def printdiff(lines):
    mapping = {
        '+': 'green',
        '-': 'red',
        '?': 'blue',
    }
    for line in lines:
        color = mapping.get(line[0])
        kw = {color: True} if color else {}
        tw.write(line, **kw)


def check_file(file, tmpdir):
    needed_updates = []
    for action in actions_of(file):
        if 'target' in action:
            py.builtin.print_(action['action'],
                repr(action['target']))

        method = globals()['do_' + action['action']]
        new_content = method(tmpdir, action)
        if new_content:
            action['new_content'] = new_content
            needed_updates.append(action)
    return needed_updates


def _main(files, should_update, rootdir=None):
    for name in files:
        tw.sep('=', 'checking %s' % (name,), bold=True)
        tmpdir = py.path.local.make_numbered_dir(
            rootdir=rootdir,
            prefix='doc-exec-')
        path = py.path.local(name)
        updates = check_file(
            file=path,
            tmpdir=path.dirpath(), #tmpdir,
        )
        if should_update:
            with open(str(path), "rb") as f:
                content = f.read()
                corrected = correct_content(content, updates)
            with open(str(path), "wb") as f:
                f.write(corrected)


def main():
    options = parser.parse_args()
    return _main(options.files, should_update=options.update)


if __name__ == '__main__':
    main()
