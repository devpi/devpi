
# original copy of this file in repo
# https://bitbucket.org/RonnyPfannschmidt/regendoc
import py
import pytest
from regendoc import blocks, correct_content
from regendoc import classify, _main
from regendoc import check_file, actions_of

from operator import itemgetter
a_c_t = itemgetter('action', 'target')

example = py.path.local(__file__).dirpath().join('example.txt')

input_data_for_blocks = """
some text
more text

next block::

    indent
      block

    with more

.. directive:: test
    :param: test

    text
"""


simple = """
an echo:
    $ echo hi
    oh no
"""

simple_corrected = simple.replace('oh no', 'hi')


def test_blocks():
    result = blocks(input_data_for_blocks.splitlines(True))
    expected = [
        # indent level, start line, lines
        (0, 1, ['some text\n', 'more text\n', '\n', 'next block::\n']),
        (4, 6, ['indent\n', '  block\n', '\n', 'with more\n']),
        (0, 11, ['.. directive:: test\n']),
        (4, 12, [':param: test\n', '\n', 'text\n']),
    ]
    py.std.pprint.pprint(result)
    assert result == expected


def test_classify_write():

    write = classify([
        '# content of test_foo.py\n',
        'def test()\n',
        '    pass\n',
    ])

    expected = {
        'action': 'write',
        'cwd': None,
        'target': 'test_foo.py',
        'content': 'def test()\n    pass\n',
        'indent': 4,
        'line': None,
    }
    assert  write == expected


def test_classify_shell():
    cmd = classify(lines=[
        '$ py.test -x\n',
        'crud\n',
    ])
    expected = {
        'action': 'shell',
        'cwd': None,
        'target': 'py.test -x',
        'content': 'crud\n',
        'indent': 4,
        'line': None,
    }
    assert cmd == expected


def test_classify_chdir_shell():
    cmd = classify(lines=[
        'testing $ echo hi\n',
        'crud\n',
    ])

    expected = {
        'action': 'shell',
        'cwd': 'testing',
        'target': 'echo hi',
        'content': 'crud\n',
        'indent': 4,
        'line': None,
    }

    assert cmd == expected

@pytest.fixture
def example(tmpdir):
    p = tmpdir.join("example.txt")
    p.write(py.std.textwrap.dedent("""\
        a simple test function call with one argument factory
        ==============================================================

        the function argument.  Let's look at a simple self-contained
        example that you can put into a test module::

            # content of: test_simplefactory.py
            def pytest_funcarg__myfuncarg(request):
                return 42

            def test_function(myfuncarg):
                assert myfuncarg == 17

        .. code-block:: bash

            $ py.test test_simplefactory.py

            output should be here - but thats nice for testing

        the end.
    """))
    return p

def test_simple_new_content(tmpdir):
    example = py.io.BytesIO(simple)
    needed_update, = check_file(
        file=example,
        tmpdir=tmpdir,
    )

    expected_update = {
        'action': 'shell',
        'cwd': None,
        'file': example,
        'target': 'echo hi',
        'content': 'oh no\n',
        'new_content': 'hi\n',
        'indent': 4,
        'line': 2,
    }
    print needed_update
    assert needed_update == expected_update


def test_single_update():

    update = {
        'action': 'shell',
        'target': 'echo hi',
        'content': 'oh no\n',
        'new_content': 'hi\n',
        'indent': 4,
        'line': 2,
    }

    corrected = correct_content(simple, [update])
    assert corrected == simple_corrected


def test_actions_of(tmpdir, example):

    actions = list(actions_of(example))

    interesting = [a_c_t(x) for x in actions]
    expected = [
        ('write', 'test_simplefactory.py'),
        ('shell', 'py.test test_simplefactory.py')]

    assert interesting == expected


def test_check_file(tmpdir, example):

    check_file(
        file=example,
        tmpdir=tmpdir,
    )
    assert tmpdir.join('test_simplefactory.py').check()


def test_main_no_update(tmpdir, example):
    _main(
        [example],
        should_update=False,
        rootdir=tmpdir,
    )
    # check for the created tmpdir
    assert tmpdir.join('doc-exec-0').check(dir=1)

def test_empty_update(tmpdir):
    simple_fp = tmpdir.join('simple.txt')
    simple_fp.write("")
    _main(
        [simple_fp],
        should_update=True,
        rootdir=tmpdir,
    )
    corrected = simple_fp.read()
    assert corrected == ""

def test_main_update(tmpdir):
    simple_fp = tmpdir.join('simple.txt')
    simple_fp.write(simple)
    _main(
        [simple_fp],
        should_update=True,
        rootdir=tmpdir,
    )
    corrected = simple_fp.read()

    assert corrected == simple_corrected


def test_docfile_chdir(tmpdir):

    tmpdir.ensure('nested/file').write('some text\n')
    example = tmpdir.join('example.txt')
    example.write('some shell test\n'
                  '  nested $ cat file\n'
                  '  some other text\n')

    action, = list(actions_of(example))
    excpected_action = {
        'action': 'shell',
        'file': example,
        'content': 'some other text\n',
        'cwd': 'nested',
        'indent': 2,
        'line': 1,
        'target': 'cat file',
    }
    assert action == excpected_action

    needed_updates = check_file(example, tmpdir)
    py.std.pprint.pprint(needed_updates)
    assert needed_updates


def test_parsing_problem(tmpdir):
    simple_fp = tmpdir.join('index.txt')
    simple_fp.write(example_index)
    _main(
        [simple_fp],
        should_update=True,
        rootdir=tmpdir,
    )
    corrected = simple_fp.read()
    assert corrected == example_index

example_index="""
py.test: no-boilerplate testing with Python
==============================================

.. toctree::
"""


def test_wipe(tmpdir):
    fp = tmpdir.join('simple.txt')
    fp.write('.. regendoc:wipe\n')
    check_file(
        file=fp,
        tmpdir=tmpdir)

    assert not tmpdir.listdir()
