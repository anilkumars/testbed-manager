Testbed Manager provides the capabilities to manage multiple machines that are included in a your testbed. It relies on an external test runner to execute user defined tests (currently using [PyreRing](http://code.google.com/p/pyrering/)), and also provides some routines to execute some test packages like LTP and UnixBench.

TestBed is written entirely in Python, of which 2.4 was the Python version it has been tested with.

TestBed currently assumes your Linux systems are Debian based, so if you need other systems supported, please make a request. With a minimal amount of work other Linux systems, as well as other Unix flavors could easily be supported.