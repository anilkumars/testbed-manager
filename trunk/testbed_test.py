#!/usr/bin/python2.4
#
# Copyright 2008 Google Inc. All Rights Reserved.

"""Tests for google3.testing.qa.ops.testbed.testbed."""

__author__ = 'kdlucas@google.com (Kelly Lucas)'

import os
import sys

from google3.pyglib import flags
from google3.testing.pybase import googletest
from google3.testing.qa.ops.testbed import testbed
from google3.testing.qa.ops.testbed import harness

FLAGS = flags.FLAGS
flags.FLAGS.threadsafe_log_fatal = False


class TestbedTest(googletest.TestCase):

  def InitYaml(self, yfile):
    """Read a yaml file into a dictionary."""
    base_dir = os.path.join(FLAGS.test_srcdir, 'google3', 'testing', 'qa',
                            'ops', 'testbed')
    self.yfile = os.path.join(base_dir, yfile)

  def ReadYFile(self):
    """Ensure a normal yaml file is parsed correctly by TestBed object."""
    self.InitYaml('test/test.yaml')
    tb = testbed.TestBed(self.yfile)
    return tb

  def testYamlParse(self):
    tbtypes = ['buildtools',
               'dapper_testing',
               'hardy_server',
               'hardy_testing',
               'kernel',
               'server_testing',
               'testing_hosts',
              ]
    jobtypes = ['accept',
                'bench',
                'ltp',
                'ltpstress',
                'net_stress',
                'system_stress',
               ]
    pkgtypes = ['accept',
                'all',
                'bench',
                'ltp',
                'ltpstress',
                'net_stress',
                'system_stress',
               ]
    consttypes = ['pathnames',
                  'filenames',
                  'roles',
                  'projects',
                  'values',
                 ]
    dtdict = {
              'baal.mtv': 'P390',
              'googol.mtv': 'Warp19',
              'namor.mtv': 'XW4300',
              'nickfury.mtv': 'T3400',
              'oshtur.mtv': 'XW4200',
              'silversurfer.mtv': 'XW4100',
             }
    apkglist = ['testbed.yaml',
                'ragent.par',
                '/home/build/static/projects/powerring/tests.tgz',
               ]
    remotehosts = ['nonexistant.mtv', 'corp.google.com']

    tb = self.ReadYFile()
    tlist = harness.GetTypes(tb.ydict, 'testbeds')
    jlist = harness.GetTypes(tb.ydict, 'jobs')
    plist = harness.GetTypes(tb.ydict, 'pkgs')
    clist = harness.GetTypes(tb.ydict, 'constants')

    # Run some tests on the Uaml file parsing using the TestBed object.
    self.assertSameElements(tbtypes, tlist)
    self.assertSameElements(jobtypes, jlist)
    self.assertSameElements(pkgtypes, plist)
    self.assertSameElements(consttypes, clist)

    hdict = harness.MakeDict(tb.ydict, 'testbeds', 'dapper_testing')
    self.assertDictEqual(dtdict, hdict)

    tempdict = harness.MakeDict(tb.ydict, 'constants')
    constants = harness.MakeConstants(tempdict)
    pkglist = harness.MakeSCPList(tb.ydict, 'accept', constants)
    self.assertSameElements(pkglist, apkglist)

    tb.GetHostList('testing_hosts')
    self.assertSameElements(tb.rhosts, remotehosts)


if __name__ == '__main__':
  googletest.main()
