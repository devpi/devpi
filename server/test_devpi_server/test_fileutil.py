from devpi_server.fileutil import BytesIO
from devpi_server.fileutil import Unserializer
from devpi_server.fileutil import dumps
from devpi_server.fileutil import loads
import pytest


# the original function
def _loads(data):
    return Unserializer(
        BytesIO(data),
        strconfig=(False, False)).load(versioned=False)


def test_execnet_opcodes():
    # we need to make sure execnet doesn't change
    assert list(Unserializer.num2func.keys()) == [
        b'@', b'A', b'B', b'C', b'D', b'E', b'F', b'G', b'H', b'I', b'J', b'K',
        b'L', b'M', b'N', b'O', b'P', b'Q', b'R', b'S', b'T']


@pytest.mark.parametrize('data, expected', [
    (b'@\x00\x00\x00\x00Q', ()),
    (b'F\x00\x00\x00\x01@\x00\x00\x00\x01Q', (1,)),
    (b'F\x00\x00\x00\x01F\x00\x00\x00\x02@\x00\x00\x00\x02Q', (1, 2)),
    (b'A\x00\x00\x00\x01aQ', b'a'),
    (b'A\x00\x00\x00\x02abQ', b'ab'),
    (b'CQ', False),
    (b'D\x00\x00\x00\x00\x00\x00\x00\x00Q', 0.0),
    (b'D\x3f\xf0\x00\x00\x00\x00\x00\x00Q', 1.0),
    (b'E\x00\x00\x00\x00Q', frozenset()),
    (b'F\x00\x00\x00\x01E\x00\x00\x00\x01Q', frozenset((1,))),
    (b'F\x00\x00\x00\x01F\x00\x00\x00\x02E\x00\x00\x00\x02Q', frozenset((1, 2))),
    (b'F\x00\x00\x00\x01Q', int(1)),
    (b'G\x00\x00\x00\x01Q', int(1)),
    (b'H\x00\x00\x00\x011Q', int(1)),
    (b'I\x00\x00\x00\x011Q', int(1)),
    (b'JQ', {}),
    (b'JF\x00\x00\x00\x00F\x00\x00\x00\x00PF\x00\x00\x00\x01F\x00\x00\x00\x02PQ', {0: 0, 1: 2}),
    (b'K\x00\x00\x00\x00Q', []),
    (b'K\x00\x00\x00\x01Q', [None]),
    (b'K\x00\x00\x00\x02Q', [None, None]),
    (b'K\x00\x00\x00\x01F\x00\x00\x00\x00F\x00\x00\x00\x01PQ', [1]),
    (b'K\x00\x00\x00\x02F\x00\x00\x00\x00F\x00\x00\x00\x01PF\x00\x00\x00\x01F\x00\x00\x00\x02PQ', [1, 2]),
    (b'K\x00\x00\x00\x01F\x00\x00\x00\x00RPQ', [True]),
    (b'K\x00\x00\x00\x01F\x00\x00\x00\x00CPQ', [False]),
    (b'LQ', None),
    (b'M\x00\x00\x00\x01aQ', b'a'),
    (b'M\x00\x00\x00\x02abQ', b'ab'),
    (b'N\x00\x00\x00\x01aQ', 'a'),
    (b'N\x00\x00\x00\x02\xc3\xa4Q', 'ä'),
    (b'O\x00\x00\x00\x00Q', set()),
    (b'F\x00\x00\x00\x01O\x00\x00\x00\x01Q', set((1,))),
    (b'F\x00\x00\x00\x01F\x00\x00\x00\x02O\x00\x00\x00\x02Q', set((1, 2))),
    (b'RQ', True),
    (b'S\x00\x00\x00\x01aQ', 'a'),
    (b'S\x00\x00\x00\x02\xc3\xa4Q', 'ä'),
    (b'T\x3f\xf0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Q', complex(1, 0)),
    (b'T\x00\x00\x00\x00\x00\x00\x00\x00\x3f\xf0\x00\x00\x00\x00\x00\x00Q', complex(0, 1)),
    (b'T\x3f\xf0\x00\x00\x00\x00\x00\x00\x3f\xf0\x00\x00\x00\x00\x00\x00Q', complex(1, 1))])
def test_loads(data, expected):
    result = loads(data)
    assert result == expected
    assert type(result) == type(expected)
    # try round-trip
    assert loads(dumps(expected)) == expected
    # compare to original
    assert result == _loads(data)
    assert _loads(dumps(expected)) == expected
