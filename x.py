
import json
from requests import request


if __name__ == "__main__":
    url = "http://localhost:8080/job/multijob/buildWithParameters"
    jsontype = "application/json"
    headers = {"Accept": jsontype, "content-type": jsontype}


    #r = request("post", url+"?devpi_index=123", headers=headers)
    #print r.status_code
    #print r.text
    #raise SystemExit(0)

    #r = request("post", url, data=json.dumps(data), headers=headers)
    r = request("post", url,
            params=dict(indexurl="http://localhost:3141/root/dev", testspec="pytest"),
            headers=headers)
    print r.status_code
    print r.text

