#!/usr/bin/python2.4
#
# Copyright 2008 Google Inc. All Rights Reserved.

"""Tests for google3.testing.qa.ops.testbed.ragent."""

__author__ = 'kdlucas@google.com (Kelly Lucas)'

import os
import shutil
import sys

from google3.pyglib import flags
from google3.pyglib import logging
from google3.testing.pybase import googletest
from google3.testing.qa.ops.testbed import ragent

FLAGS = flags.FLAGS
flags.FLAGS.threadsafe_log_fatal = False


class RagentTest(googletest.TestCase):

  def InitYaml(self, yfile):
    """Read a yaml file into a dictionary."""
    base_dir = os.path.join(FLAGS.test_srcdir, 'google3', 'testing', 'qa',
                            'ops', 'testbed')
    self.yfile = os.path.join(base_dir, yfile)

  def CheckLogNames(self, runpath, config, job, operation, project, logname):
    """Ensure that GetLogs finds the correct log files.

    Args:
      runpath: string, pathname of where program executes from.
      config: yaml config file name.
      job: string, the name of a job.
      operation: string, name of operation.
      project: string, name of project.
      logname: the name of the test log we have in place.
    """
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    logsrc = os.path.join(ra.constants['GTEMP'], logname)
    logs = ra._GetLogs()
    self.assertEqual(logs['logsrc'], logsrc)
    self.assertEqual(logs['rptsrc'], logsrc)

  def testRemoteAgentConfig(self):
    """Test a Remote Agent Object."""

    project = "goobuntu"
    temppath = os.path.dirname(sys.argv[0])
    runpath = os.path.abspath(temppath)
    config = os.path.join(runpath, 'test/test.yaml')
    sudofile = os.path.join(runpath, 'test/sudoers')
    backupfile = '/tmp/sudoers'
    user = 'testuser'
    job = 'accept'
    operation = 'config'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.Config(user, sudofile)

    f = open(sudofile, 'r')
    text = f.read()
    f.close()
    index = text.count(user)
    self.assertEqual(index, 1)

    # Ensure Config() doesn't add the same user twice.
    ra.Config(user, sudofile)
    f = open(sudofile, 'r')
    text = f.read()
    f.close()
    index = text.count(user)
    self.assertEqual(index, 1)

    # Ensure we made a backup of the sudoers file.
    filestatus = os.access(backupfile, 2)
    self.assertEqual(filestatus, True)

    try:
      shutil.copy(backupfile, sudofile)
    except IOError, e:
      logging.error('Error restoring %s file', sudofile)

    job = 'ltp'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.ltp_home = ragent.harness.GetLTPHome(ra.constants['GTEMP'])
    logs = ra._GetLogs()
    logsrc = os.path.join(runpath, 'test/ltp-full-20080229/output/blade.html')
    rptsrc = os.path.join(runpath, 'test/ltp-full-20080229/results/log.ltp')
    self.assertEqual(logs['logsrc'], logsrc)
    self.assertEqual(logs['rptsrc'], rptsrc)

    job = 'ltpstress'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.ltp_home = ragent.harness.GetLTPHome(ra.constants['GTEMP'])
    logsrc = os.path.join(ra.constants['GTEMP'], 'testlog.slog')
    logs = ra._GetLogs()
    self.assertEqual(logs['logsrc'], logsrc)
    self.assertEqual(logs['rptsrc'], logsrc)

    job = 'accept'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.constants['LSBFILE'] = os.path.join(runpath, 'test/lsb-release')
    lines = ra._ReadFile(ra.constants['LSBFILE'])
    ra._GetSuite(lines)
    logs = ra._GetLogs()
    rptsrc = os.path.join(ra.constants['GTEMP'], 'reports/testlog.txt')
    logsrc = os.path.join(ra.constants['GTEMP'], 'reports/powerring.log')
    self.assertEqual(ra.suitefile, 'wks_dapper_accept.suite')
    self.assertEqual(logs['logsrc'], logsrc)
    self.assertEqual(logs['rptsrc'], rptsrc)

    job = 'bench'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    # ra.constants['BENCHLOG'] gets set when the RemoteAgent object is
    # initialized, so we need to go back and reset this value using the new
    # GTEMP value.
    ra.constants['BENCHLOG'] = os.path.join(ra.constants['GTEMP'],
                                            'unixbench-5.1.2', 'results',
                                            'report')
    logs = ra._GetLogs()
    logsrc = os.path.join(ra.constants['GTEMP'],
                          'unixbench-5.1.2/results/report.html')
    self.assertEqual(logs['logsrc'], logsrc)

    self.CheckLogNames(runpath, config, 'net_stress', operation, project,
                       'testlog.netperf')
    self.CheckLogNames(runpath, config, 'system_stress', operation, project,
                       'testlog.system')

    job = 'ltp'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.ltp_home = ragent.harness.GetLTPHome(ra.constants['GTEMP'])
    ra._RunInventory()

    job = 'bench'
    ra = ragent.RemoteAgent(runpath, config, job, operation, project)
    ra.constants['GTEMP'] = os.path.join(runpath, 'test')
    ra.constants['BENCHLOG'] = os.path.join(ra.constants['GTEMP'],
                                            'unixbench-5.1.2', 'results',
                                            'report')
    logs = ra._GetLogs()
    ra._ProcessUnixBench(logs)


if __name__ == '__main__':
  googletest.main()
