#!/usr/bin/python
#
# Copyright 2010 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Entry point for the TestBed package.

TestBed controls the the execution of test jobs against a testbed. TestBed
executes the following logic flow:
  1) Parses command line flags to determine actions
  2) Acquires a testbed, which is a list of machines that are available and
     qualified to run.
  3) Send the proper tests in the selected test job to each host in the
     testbed, and starts the execution of it.
  4) Uses PyreRing to execute acceptance tests. (You can easily replace
     PyreRing with a runner of your choice by simply adding in your 
     runner and creating a method for it in the Runner class. See the Runner
     class in ragent.py, and call your new method.

The following classes are used to organize data and methods:
  TestBed - Manages interactions with TestBed definitions and lists. Module
            entry point. Manages jobs, which make up a test, and sends files
            and initiates ragent on the remote systems under test.
  RemoteAgent - The class that manages all processes on remote systems.
                This is the module that will execute test suites on each of the
                systems.

A yaml file (testbed.yaml) is used to hold data on:
  TestBeds: testbeds are named and defined by listing a name and all hostnames
            that are members of that test bed.
  Jobs: job names are matched to the suite file name.
  Platforms: for later use.
  Constants: various user defined constants are defined. A user may have need
             to change some of these values, especially: ROOT, MAILTO, ROLE,
             and REPORTHOST. Many additional constants are built using some of
             these initial values.
harness.py - Utility functions that all modules depend on and use.
"""

__author__ = 'kdlucas@google.com (Kelly Lucas)'
__version__ = '1.0.0'

import getpass
import logging
import optparse
import os
import sys
import time

import harness


class TestBed(object):
  """Static data structure for testbeds.

  A lightweight object to manage some static data from an external yaml file.
  Parse yaml file, grab lists of hosts based on some filter criteria.

  ShowRecords(), GetHostList(), and GetConstants() are primarily debugging
  methods and informational routines to help users who need to debug a yaml
  file or learn about the contents of their yaml file.
  """

  def __init__ (self):
    """Parse command line options and the yaml config file.
       
       Open yaml file and parse it using the yaml module.

    Args:
      All of the following options arguments are supported.
    """

    parser = optparse.OptionParser()
    parser.add_option('-c', '--config',
                      dest='yaml',
                      default='testbed.yaml',
                      help='Specify configuration file (yaml format)')
    parser.add_option('-d', '--debug',
                      dest='debug',
                      default='info',
                      type='choice',
                      choices=['debug', 'info', 'warning', 'error', 'critical'],
                      help='Specify debug log level')
    parser.add_option('--display',
                      dest='display',
                      type='choice',
                      choices=['constants', 'jobs', 'testbeds'],
                      help='Specify what to display from config file')
    parser.add_option('--host',
                      dest='remote_host',
                      help='Remote host to run tests on.')
    parser.add_option('-j', '--job',
                      dest='job',
                      type='choice',
                      choices=['accept', 'all', 'bench', 'dbench', 'ltp',
                               'ltpstress', 'net_stress', 'system_stress'],
                      help='Specify job type')
    parser.add_option('-o', '--op',
                      dest='op',
                      type='choice',
                      choices=['auto', 'clean', 'config', 'display', 'get',
                               'halt', 'install', 'query', 'reboot', 'run',
                               'update', 'version'],
                      help='Type of operation')
    parser.add_option('--pkg',
                      dest='pkg',
                      help='Specify package name to install.')
    parser.add_option('-r', '--reports',
                      dest='reports',
                      default=os.path.join(sys.path[0], 'reports'),
                      help='Specify the report directory, default is ./reports')
    parser.add_option('-t', '--testbed',
                      dest='testbed',
                      help='Specify the testbed(list of machines).')

    self.options, self.args = parser.parse_args()

    logfile = os.path.join(self.options.reports, 'testbed.log')
    if not harness.SetReports(self.options.reports, logfile):
      print 'Error creating report directory or with existing log files.'
      print 'Check the %s directory for permissions' % self.options.reports
      sys.exit(1)
    self.logger = harness.SetLogger('TestBed', logfile, self.options.debug)

    self.ydict = harness.ReadYamlFile(self.options.yaml)
    self.rhosts = []
    username = getpass.getuser()
    self.constants = {}
    tempdict = harness.MakeDict(self.ydict, 'constants')
    tempdict['ROOT'] = os.path.join(tempdict['ROOT'], username)
    self.constants = harness.MakeConstants(tempdict)
    self.testbeds = self.ydict['testbeds'].keys()
    self.jobs = harness.GetTypes(self.ydict, 'jobs')

    self._CheckOptions()


    self.testbed_ops = {
        'halt': ['sudo halt'],
        'reboot': ['sudo reboot'],
        'update': ['sudo apt-get update',
                   'sudo apt-get upgrade -f -y --force-yes',
                   'sudo reboot']}

    pingcmd = 'ping -c 2 '
    # Rebuild the self.rhosts lists with only hosts that answer ping.
    rhosts = self.rhosts
    self.rhosts = []
    for rhost in rhosts:
      self.logger.info('Checking %s', rhost)
      cmd = pingcmd + rhost
      if harness.ExecGetOutput(cmd):
        self.rhosts.append(rhost)

  def _CheckOptions(self):
    """Check options arguments for sane values and correct usage."""
    if not self.options.op:
      self.logger.warning('Usage error: op is required.')
      Usage()
    if self.options.op in ['auto', 'get', 'query', 'run']:
      if not self.options.job:
        self.logger.warning('Operation %s specified.', self.options.op)
        self.logger.warning('Operation requires a job name.')
        Usage()
    
    if self.options.op == 'display':
      if not self.options.display:
        self.logger.warning('Operation display requires --display.')
        Usage()
    else:
      if self.options.testbed:
        if self.options.testbed in self.testbeds:
          self.GetHostList(self.options.testbed)
        else:
          self.logger.warning('You specified an undefined testbed.')
          self.logger.warning('Defined testbeds: \n%s',
              '\n'.join(sorted(self.testbeds)))
          self.logger.warning('Correct testbed name or define a new one.')
          sys.exit(1)
      elif self.options.remote_host:
        self.rhosts.append(self.options.remote_host)
      else:
        self.logger.warning('Usage error: --testbed or --host must be used.')
        Usage()

  def ShowRecords(self, query):
    """Display a list of items from the testbed config file.

    Args:
      query: string, specifies which type of records to display.
    """

    if self.ydict.has_key(query):
      for name in self.ydict[query]:
        print '=' * 30
        print 'Name: %s' % name
        print '=' * 30
        for suite in self.ydict[query][name]:
          for item in suite:
            print 'Name: %s' % item
            print 'Value: %s' % suite[item]
    else:
      logging.error('Warning, %s is an unknown type of record.', query)

  def GetHostList(self, query):
    """Create a host list from the specified testbed.

    Args:
      query: string, specifies the testbed name.
    Returns:
      list of hostnames from specified testbed.
    """

    print 'Testbed Name: %s' % query
    for tb in self.ydict['testbeds'][query]:
      for rhost in tb:
        self.rhosts.append(rhost)

  def GetConstants(self):
    """Display the keys and values of self.constants."""

    for key in self.constants:
      print '%s: %s' % (key, self.constants[key])

  def GetVersion(self):
    """Get kernel version and GOOGLE_RELEASE string.

    This method will get the Goobuntu version strings.
    TODO(kdlucas): determine if this should be done by harness.GetVersion().
    """

    cmds = {'kernel': '"uname -r"',
            'arch': '"uname -m"',
            'Distribution':
            "grep DISTRIB_ID /etc/lsb-release | awk -F'=' '{print $2}'",
            'Release':
            "grep DISTRIB_RELEASE /etc/lsb-release | awk -F'=' '{print $2}'",
            'Codename':
            "grep DISTRIB_CODENAME /etc/lsb-release | awk -F'=' '{print $2}'",
            'Description':
            "grep DESCRIPTION /etc/lsb-release | awk -F'=' '{print $2}'",
           }

    for rhost in self.rhosts:
      self.logger.info('Getting version for: %s' % rhost)
      for key in cmds:
        cmd = 'ssh %s %s' % (rhost, cmds[key])
        self.logger.info(key)
        cmdoutput = harness.ExecGetOutput(cmd, output=True)
        print cmdoutput

  def CheckVersion(self, rhost, job):
    """Check RELEASE in /etc/lsb-release versus our own test file.

    Args:
      rhost: string, the name of the remote host to check.
      job: string, represents the type of tests to run.
    Returns:
      boolean: True if release strings match, False = don't match.

    This method will compare the value of GOOGLE_RELEASE in /etc/lsb-release
    versus a file we create: /var/tmp/test.run This file will contain the
    GOOGLE_RELEASE string of Goobuntu when we last ran acceptance tests.
    """

    lsbfile = '/etc/lsb-release'
    runfile = '/var/tmp/%s.run' % job
    cmds = {'update': '"sudo apt-get update"',
            'google_release':
            "grep DISTRIB_RELEASE %s | awk -F'=' '{print $2}'" % lsbfile,
            'last_testrun':
            "grep DISTRIB_RELEASE %s | awk -F'=' '{print $2}'" % runfile,
           }

    write_cmd = 'grep DISTRIB_RELEASE /etc/lsb-release > %s' % runfile

    for key in cmds:
      cmd = 'ssh %s %s' % (rhost, cmds[key])
      cmdoutput = harness.ExecGetOutput(cmd, output=True)
      print cmdoutput
      if key == 'google_release':
        grel = cmdoutput
      elif key == 'last_testrun':
        lrun = cmdoutput

    if grel == lrun:
      self.logger.info('Tests were already run on %s with this release.', rhost)
      return True
    else:
      cmd = 'ssh %s "%s"' % (rhost, write_cmd)
      harness.ExecGetOutput(cmd)
      return False

  def AutoRun(self, job):
    """Remove rhosts if tests have already been run on this release.

    Args:
      job: string, represents type of tests to run.
    """

    removehosts = set()

    for rhost in self.rhosts:
      if self.CheckVersion(rhost, job):
        removehosts.add(rhost)
      else:
        self.logger.info('Rebooting %s to prep for testing.', rhost)
        cmd = 'ssh %s %s' % (rhost, 'sudo reboot')
        harness.ExecGetOutput(cmd)
    for rhost in removehosts:
      self.rhosts.remove(rhost)

  def TestBedOp(self, op):
    """Run operation on testbed specified by op."""

    if op in self.testbed_ops:
      cmds = self.testbed_ops[op]
    else:
      self.logger.error('Unknown operation: %s', op)
      return

    for rhost in self.rhosts:
      self.logger.info('Running %s on %s', op, rhost)
      for cmd in cmds:
        sshcmd = 'ssh %s %s' % (rhost, cmd)
        if not harness.ExecGetOutput(sshcmd):
          self.logger.error('Error running %s on %s', op, rhost)

  def Prepare(self, op, job=None):
    """Prepare the remote host to run the job.

    Args:
      op: string, the type of operation to run.
      job: string, the name of the job to run.
    Perform the preparatory work to perform the operation specified by op.
    run:
      scp required programs and files to remote hosts.
    get|query|configure:
      scp ragent.py, as that is the only needed file.
    halt|reboot|update:
      all commands are issued via JobMgr using ssh, and no files are needed.
    Summary of execution:
      1) Check remote host for self.constants['ROOT'] directory.
      2) Copy necessary files to accept homedir
    I use subprocess.call when I only care about the return code, and
    subprocess.Popen (from harness.ExecGetOutput) when stdout and stderr may
    have useful info.
    """

    removehosts = set()
    # Ensure a local ROOT exists on the server for writing log files.
    tempdir = os.path.join(self.constants['ROOT'], 'tmp')
    if not os.path.exists(tempdir):
      try:
        os.makedirs(tempdir)
      except IOError, e:
        self.logger.error('Error creating %s\n%s', tempdir, e)
        self.logger.warning('Runtime test data will not be logged.')

    # sshcmds is a list of commands that will be run on each remote host.
    # TODO(kdlucas): put all shell commands in a wrapper class, and call
    # wrapper to execute them. Place needed commands in yaml file similar to
    # the pkgs tree.
    if op in ['auto', 'config', 'get', 'query', 'run']:
      sshcmds = ['mkdir -m 1775 -p ' + tempdir]
      if job:
        if job in self.jobs or job == 'all':
          self.scppkgs = harness.MakeSCPList(self.ydict, job, self.constants)
        else:
          self.logger.error('Invalid job name: %s', job)
      else:
        self.scppkgs = [
                        self.constants['CONFIG'],
                        self.constants['HARNESS'],
                        self.constants['PUBKEY'],
                        self.constants['REMOTEAGENT'],
                       ]
      for rhost in self.rhosts:
        self.logger.info('Preparing %s', rhost)
        for command in sshcmds:
          cmd = 'ssh %s %s' % (rhost, command)
          status = harness.ExecCall(cmd)
          if not status:
            self.logger.error('Error executing %s', cmd)
        for pkg in self.scppkgs:
          cmd = 'scp -p %s %s:%s' % (pkg, rhost, self.constants['ROOT'])
          if not harness.ExecGetOutput(cmd):
            removehosts.add(rhost)
      for rhost in removehosts:
        self.logger.error('Copy file error, removing %s from testbed', rhost)
        self.rhosts.remove(rhost)
    else:
      return

  def Configure(self):
    """Configure all remote hosts for automated testing.

    This will configure all of the systems in a given testbed to allow sudo
    without a password, and install all required packages for various test
    suites. This procedure will require users to enter their password the
    first time it is run.
    The configuration file should have pathnames[PUBKEY] set to your public key,
    that will be used to set up ssh without a password.
    """

    pkfile = os.path.basename(self.constants['PUBKEY'])

    self.logger.info('Configuring system for automated testing.')
    yamlfile = os.path.join(self.constants['ROOT'], 'testbed.yaml')
    pkeyfile = os.path.join(self.constants['ROOT'], pkfile)

    pw = getpass.getpass()

    pkglist = harness.MakeDict(self.ydict, 'packages', 'testbed')
    for rhost in self.rhosts:
      self.logger.info('Installing required packages on %s', rhost)
      for pkg in pkglist:
        command = 'sudo -S apt-get -y --force-yes install %s' % pkg
        cmd = 'echo %s | ssh %s %s' % (pw, rhost, command)
        if not harness.ExecGetOutput(cmd, input=True):
          logging.error('Error installing %s on %s', pkg, rhost)

    command = os.path.join(self.constants['ROOT'], 'ragent.py')
    for rhost in self.rhosts:
      cmd = ''.join([
          'echo %s | ssh %s sudo -S %s' % (pw, rhost, command),
          ' --config %s' % yamlfile,
          ' --op config',
          ' --pubkey %s' % pkeyfile,
          ' --user %s' % self.constants['TESTER']])
      self.logger.info('Configuring host: %s', rhost)
      if not harness.ExecGetOutput(cmd, input=True):
        logging.error('Error configuring %s', rhost)

  def Install(self, pkg):
    """Install a package on all hosts.

    Args:
      pkg: string, name of package to install.
    """

    for rhost in self.rhosts:
      cmd = 'ssh %s sudo apt-get install -y --force-yes %s' % (rhost, pkg)
      self.logger.info('Executing: %s', cmd)
      harness.ExecGetOutput(cmd)

  def Clean(self):
    """Remove files from previous test runs.

    Returns:
      boolean: true = success, false = failure
    """

    status = True

    for rhost in self.rhosts:
      cmd = 'ssh %s sudo rm -rf %s' % (rhost, self.constants['ROOT'])
      self.logger.info('Executing: %s', cmd)
      if not harness.ExecGetOutput(cmd):
        status = False

    return status

  def RunJob(self, job, op):
    """Send the command to all hosts in rhosts to run tests."""

    if not job:
      self.logger.warning('Job must be set to call Run().')
      return 1
    if not op:
      self.logger.warning('Operation must be set to call Run().')
      return 1

    command = os.path.join(self.constants['ROOT'], 'ragent.py')
    yamlfile = os.path.join(self.constants['ROOT'], self.options.yaml)


    for rhost in self.rhosts:
      runlog = os.path.join(self.constants['ROOT'], '%s.%s') % (rhost, job)
      # The source to the runner must be extracted before ragent runs.
      if job == 'accept':
        runner_src = os.path.basename(self.constants['RUNNER'])
        runner_path = os.path.join(self.constants['ROOT'], runner_src)
        cmd = 'ssh %s "tar -zxvf %s -C %s"' % (rhost, runner_path,
                                               self.constants['ROOT'])
        self.logger.info('Executing: %s' % cmd)
        harness.ExecGetOutput(cmd)
      cmd = ''.join([
          'ssh -f %s %s' % (rhost, command),
          ' --config %s' % yamlfile,
          ' --op %s' % op,
          ' --job %s' % job,
          ' > %s' % runlog])
      self.logger.info('executing: %s' % cmd)
      harness.ExecGetOutput(cmd)

  def Run(self):
    """Run the jobs in a suite."""

    self.Prepare(op=self.options.op, job=self.options.job)
    self.logger.info('Running operation: %s', self.options.op)
    if self.options.op == 'clean':
      self.Clean()
    elif self.options.op == 'config':
      self.Configure()
    elif self.options.op == 'install':
      self.Install(self.options.pkg)
    elif self.options.op == 'auto':
      self.AutoRun(self.options.job)
      # Give the machines time to reboot
      logging.info('Pausing to allow target systems time to reboot')
      time.sleep(self.constants['REBOOTTIME'])
      self.RunJob(job=self.options.job, op='run')
    elif self.options.op == 'version':
      self.GetVersion()
    elif self.options.job:
      logging.info('Running operation: %s and job %s', self.options.op,
                   self.options.job)
      self.RunJob(job=self.options.job, op=self.options.op)
    else:
      self.TestBedOp(op=self.options.op)


def Usage():
  """Usage requirements and parameters.

  --help for parameter details.
  Required parameters:
    --host <hostname> (run on remote host, mutually exclusive with --testbed)
    -t --testbed <testbed_name> (use --show testbed to show all testbeds)
    -j --job <accept | all | bench | dbench | ltp | ltpstress | net_stress |
              srcfs | system_stress>
    --op <auto|clean|config|display|get|halt|install|query|reboot|run|update|
          version> (type of operation)
    Note: --testbed and --remote_host are mutually exclusive.
          --job is required when op = get, query, run, or auto.
          --display is required when op = display.
  Optional parameters:
    --d --debug (speicfy debug log level, default is info)
    --display <constants|jobs|testbeds> (what category of items to display)
    --pkg <package_name> (specify package to install)
    -v --version (Display the version of this TestBed module)
    -c --config (Specify the yaml dictionary file. Defaults to 'testbed.yaml')
  """

  print Usage.__doc__
  sys.exit(1)


def main(argv):
  if len(argv) < 1:
    Usage()
  tb = TestBed()
  
  if tb.options.op == 'display':
    tb.ShowRecords(tb.options.display)
    return 0
  else:
    tb.Run()


if __name__ == '__main__':
  main(sys.argv)
