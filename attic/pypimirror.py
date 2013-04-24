
def fetch(url):
    import time
    res = timeout = 10.0
    now = time.time()
    print "fetching", url
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
    except requests.exceptions.RequestException:
        res = timeout + 1
    else:
        if r.status_code == 200:
            res = time.time() - now
    client.zadd(key, timeout-res, url)

if __name__ == "__main__":
    import eventlet
    eventlet.monkey_patch()
    import redis
    import requests
    key = "pypimirrors"
    client = redis.StrictRedis()
    client.delete(key)
    pool = eventlet.GreenPool(20)

    for i in range(ord("b"), ord("g") + 1):
        c = chr(i)
        if c in "bde":
            continue
        url = "http://%s.pypi.python.org/packages/" % chr(i)
        pool.spawn_n(fetch, url)
    pool.waitall()
    for x in client.zrange(key, 0, 10, withscores=True):
        print x
