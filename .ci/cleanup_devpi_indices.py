from requests import Session
import datetime
import subprocess
import sys


MAXDAYS = 14


session = Session()
session.headers["Accept"] = "application/json"


def get_indexes(baseurl: str, username: str) -> dict:
    response = session.get(baseurl + username)
    assert response.status_code == 200
    result = response.json()["result"]
    return result["indexes"]


def get_projectnames(baseurl: str, username: str, indexname: str) -> list:
    response = session.get(baseurl + username + "/" + indexname)
    assert response.status_code == 200
    result = response.json()["result"]
    return result["projects"]


def get_release_dates(baseurl: str, username: str, indexname: str, projectname: str) -> set:
    response = session.get(baseurl + username + "/" + indexname + "/" + projectname)
    assert response.status_code == 200
    result = response.json()["result"]
    dates = set()
    for value in result.values():
        for link in value.get("+links", []):
            for log in link.get("log", []):
                dates.add(tuple(log["when"]))
    return dates


def run() -> None:
    baseurl = "https://m.devpi.net/"
    username = "devpi-github"
    for indexname in get_indexes(baseurl, username):
        projectnames = get_projectnames(baseurl, username, indexname)
        all_dates = set()
        for projectname in projectnames:
            dates = get_release_dates(baseurl, username, indexname, projectname)
            if not dates:
                print(
                    "%s has no releases" % (baseurl + username + "/" + indexname),
                    file=sys.stderr)
            else:
                all_dates = all_dates.union(dates)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        if all_dates:
            date = datetime.datetime(*max(all_dates), tzinfo=datetime.timezone.utc)
        else:
            date = now
        if (now - date) > datetime.timedelta(days=MAXDAYS):
            assert username
            assert indexname
            url = baseurl + username + "/" + indexname
            subprocess.check_call(["devpi", "index", "-y", "--delete", url])


if __name__ == '__main__':
    run()
