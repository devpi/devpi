import hashlib


tox_result_data = {
    "reportversion": "1", "toxversion": "1.6",
    "platform": "linux2",
    "host": "foo",
    "installpkg": {
        "basename": "pytest-1.7.zip",
        "md5": hashlib.md5(b"123").hexdigest(),
        "sha256": hashlib.sha256(b"123").hexdigest(),
    },
    "testenvs": {
        "py27": {
            "test": [{
                "command": ["python"],
                "retcode": "0",
                "output": "everything fine",
            }]
        }
    }
}
