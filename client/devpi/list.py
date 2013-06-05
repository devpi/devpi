
def main(hub, args):
    r = hub.http.get(hub.config.rooturl)
    if r.status_code == 200:
        hub.info("list of users and indexes")
        data = r.json()["resource"]
        for user in sorted(data):
            userconfig = data[user]
            indexes = userconfig.pop("indexes", None)
            info = " ".join(["%s=%s" % item for item in userconfig.items()])
            hub.line("%s/  %s" %(user, info))
            if indexes:
                for index in sorted(indexes):
                    indexconfig = indexes[index]
                    hub.line("  %s: %s bases=%s  volatile=%s" %(
                             index, indexconfig["type"],
                             indexconfig["bases"],
                             indexconfig["volatile"]))
    else:
        hub.error("failed to get list of users, server returned %s: %s" %(
                  r.status_code, r.reason))
        return 1
