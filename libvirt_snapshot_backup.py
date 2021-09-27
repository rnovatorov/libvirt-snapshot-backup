import contextlib
import time
import xml.etree.ElementTree as xml_element_tree

import libvirt


DOMAIN_NAME = "win10"
SNAPSHOT_PREFIX = "bak_"
SNAPSHOT_COUNT = 3


def main():
    with Connection.system() as conn:
        dom = conn.domain_by_name(DOMAIN_NAME)
        create_snapshot(dom, SNAPSHOT_PREFIX)
        rotate_snapshots(dom, SNAPSHOT_PREFIX, SNAPSHOT_COUNT)


def create_snapshot(dom, prefix):
    with temporarily_shutdown_domain(dom):
        name = f"{prefix}{int(time.time())}"
        dom.create_snapshot(name, atomic=True)


def rotate_snapshots(dom, prefix, count):
    assert count > 0
    snaps = [snap for snap in dom.list_snapshots() if snap.name().startswith(prefix)]
    if len(snaps) <= count:
        return
    snaps.sort(key=lambda snap: snap.timestamp())
    for snap in snaps[:-count]:
        snap.delete()


class Connection:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        self._conn.__exit__(*exc)

    def domain_by_name(self, name):
        dom = self._conn.lookupByName(name)
        return Domain(dom=dom)

    @classmethod
    def system(cls):
        return cls.open("qemu:///system")

    @classmethod
    def open(cls, uri):
        conn = libvirt.open(uri)
        return Connection(conn=conn)


class Domain:
    def __init__(self, dom):
        self._dom = dom

    def is_up(self):
        (state, _) = self._dom.state()
        return state == libvirt.VIR_DOMAIN_RUNNING

    def is_down(self):
        (state, _) = self._dom.state()
        return state == libvirt.VIR_DOMAIN_SHUTOFF

    def down(self, timeout=30):
        if not self.is_up():
            return
        self._dom.shutdown()
        wait(lambda: self.is_down(), timeout=timeout)

    def up(self):
        self._dom.create()

    def create_snapshot(self, name="", atomic=False):
        desc = f"""<domainsnapshot>
            <name>{name}</name>
        </domainsnapshot>"""
        flags = 0
        if atomic:
            flags |= libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC
        self._dom.snapshotCreateXML(desc, flags)

    def list_snapshots(self):
        return [Snapshot(snap=snap) for snap in self._dom.listAllSnapshots()]


class Snapshot:
    def __init__(self, snap):
        self._snap = snap
        self._desc = xml_element_tree.fromstring(self._snap.getXMLDesc())

    def name(self):
        return self._snap.getName()

    def timestamp(self):
        elems = [elem for elem in self._desc if elem.tag == "creationTime"]
        assert len(elems) == 1
        return int(elems[0].text)

    def delete(self):
        self._snap.delete()


@contextlib.contextmanager
def temporarily_shutdown_domain(dom):
    dom.down()
    try:
        yield
    finally:
        dom.up()


def wait(func, timeout):
    t0 = time.monotonic()
    while not func():
        t1 = time.monotonic()
        elapsed = t1 - t0
        if elapsed >= timeout:
            raise TimeoutError
        time.sleep(1)


if __name__ == "__main__":
    main()
