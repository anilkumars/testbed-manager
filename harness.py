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

"""Library of routines used by the TestBed package.

Various classes will need access to these shared functions. Depends on
testbed.yaml, which provides constants which can be edited by users.
"""

__author__ = 'kdlucas@gmail.com (Kelly Lucas)'

import datetime
import fileinput
import getpass
import glob
import logging
import os
import platform
import shutil
import subprocess
import tarfile

import MySQLdb
import yaml


def MakeConstants(cdict):
  """Construct all of the necessary variables needed by TestBed.

  Args:
    cdict: dictionary of constants.
  Returns:
    dictionary of constructed variables.

  Note that vdict relies on local machine variables to construct its various
  variables, and often will join local variables with constants in cdict.
  """

  vdict = {}
  vdict.update(cdict)
  username = getpass.getuser()
  # vdict['ROOT'] = os.path.join(cdict['ROOT'], username)
  # vdict['ROOT'] = os.path.dirname(os.path.abspath(sys.argv[0]))
  vdict['ROLEHOME'] = os.path.expanduser('~' + cdict['ROLE'])
  vdict['RPTHOME'] = os.path.join(vdict['ROLEHOME'], 'www')
  vdict['APPS'] = os.path.join(vdict['ROLEHOME'], 'tests')
  vdict['ACCEPTTARGET'] = os.path.join(vdict['RPTHOME'], 'accept')
  vdict['AIMBIN'] = os.path.join(vdict['APPS'], 'benchmark', vdict['AIM'])
  vdict['AIMHOME'] = os.path.join(vdict['ROOT'], 'aim')
  vdict['AIMLOG'] = os.path.join(vdict['AIMHOME'], 'aim9', 'suite9.ss')
  vdict['AIMTARGET'] = os.path.join(vdict['RPTHOME'], 'perf')
  vdict['BUILDHOME'] = os.path.join(vdict['ROOT'], 'builds')
  vdict['BUILDTARGET'] = os.path.join(vdict['RPTHOME'], 'builds')
  cdict['BENCHBIN'] = os.path.join(vdict['APPS'], 'benchmark', vdict['BENCH'])
  vdict['BENCHBIN'] = cdict['BENCHBIN'] + '.tgz'
  vdict['BENCHHOME'] = os.path.join(vdict['ROOT'], 'unixbench-5.1.2')
  vdict['BENCHLOG'] = os.path.join(vdict['BENCHHOME'], 'results', 'report')
  vdict['BENCHTARGET'] = os.path.join(vdict['RPTHOME'], 'perf')
  vdict['HOURS'] = 72
  cdict['LTPBIN'] = os.path.join(vdict['APPS'], 'ltp', vdict['LTP'])
  vdict['LTPBIN'] = cdict['LTPBIN'] + '.tgz'
  vdict['LTPHOME'] = os.path.join(vdict['ROOT'], 'ltp')
  vdict['LTPPID'] = os.path.join(vdict['ROOT'], 'ltp.pid')
  vdict['LTPTARGET'] = os.path.join(vdict['RPTHOME'], 'ltp')
  # Hard coded to hardy tests for now, but will be replaced by a dynamic
  # mechanism to determine which tests file to use.
  vdict['PERFHOME'] = os.path.join(vdict['ROOT'], 'perf')
  vdict['SRCDIR'] = os.path.join(vdict['ROOT'], 'tests', 'testcases')
  vdict['STRESSHOME'] = os.path.join(vdict['ROOT'], 'stress')
  vdict['STRESSTARGET'] = os.path.join(vdict['RPTHOME'], 'stress')
  vdict['TESTER'] = username
  vdict['URLHOME'] = 'http://king:8000/media/logs'

  return vdict


def ReadYamlFile(yamlfile):
  """Read a yaml file and return a dict tree of the data."""

  try:
    f = open(yamlfile, 'r')
    try:
      try:
        ydict = yaml.load(f)
      except IOError, e:
        print('Error parsing %s', yamlfile)
    finally:
      f.close()
  except IOError, e:
    print('Cannot open file %s', yamlfile)

  return ydict


def SetReports(reportdir, logfile):
  """A function to setup the report directory and backup existing logfiles.

  Args:
    reportdir: directory for log files.
    logfile: filename for logging.
  Returns:
    boolean: True is successful, False if errors encountered.
  """
  status = True
  # Make the reports directory if it doesn't exist.
  if not os.path.exists(reportdir):
    try:
      os.mkdir(reportdir)
    except IOError, e:
      print(e)
      status = False
  # Backup any existing log files.
  if os.path.exists(logfile):
    newlog = logfile + '.' + GetTimeString()
    try:
      os.rename(logfile, newlog)
    except IOError, e:
      print(e)
      status = False

  return status


def SetLogger(namespace, logfile, loglevel):
  """A function to set up a logger.
  This function will send messages to a log file and the console.

  Args:
    Filename of log file, which should be an absolute pathname.
  Returns:
    Logger object.
  """
  logger = logging.getLogger(namespace)
  c = logging.StreamHandler()
  h = logging.FileHandler(logfile)
  hf = logging.Formatter('%(asctime)s %(process)d %(levelname)s: %(message)s')
  cf = logging.Formatter('%(levelname)s: %(message)s')
  logger.addHandler(h)
  logger.addHandler(c)
  h.setFormatter(hf)
  c.setFormatter(cf)

  if loglevel == 'debug':
    logger.setLevel(logging.DEBUG)
  elif loglevel == 'info':
    logger.setLevel(logging.INFO)
  elif loglevel == 'warning':
    logger.setLevel(logging.WARNING)
  elif loglevel == 'error':
    logger.setLevel(logging.ERROR)
  elif loglevel == 'critical':
    logger.setLevel(logging.CRITICAL)
  else:
    logger.setLevel(logging.INFO) # Shouldn't get to here, but just in case.

  return logger


def ReplaceText(old, new, textfile):
  """Replace a string in a textfile.

  Args:
    old: string, existing string to replace.
    new: string, new string to replace the old string, if found.
    textfile: string, filename to perform the search and replace in.
  Returns:
    boolean: True if successful, False if errors encountered.
  If no pathname is given to textfile, assume file is in cwd.
  """

  try:
    for line in fileinput.FileInput(textfile, inplace=True):
      line = line.strip()
      line = line.replace(old, new)
      print line
    status = True
  except IOError, e:
    print('Error accessing %s during ReplaceText().', textfile)
    print(e)
    status = False

  return status


def ExecCall(cmd):
  """Run subprocess.call and do not capture stdout/stderr.

  Args:
    cmd: string that represents command and all arguments.
  Returns:
    boolean: True = success, False = errors.
  """

  status = True
  rc = subprocess.call(cmd, shell=True, stdout=subprocess.PIPE)
  if rc:
    print('Error executing %s', cmd)
    status = False
  return status


def ExecGetOutput(cmd, input=None, output=None):
  """Run subprocess.Popen and send stdout/stderr to a PIPE.

  Args:
    cmd: string that represents command and all arguments.
    input: boolean, True = input required.
    output: boolean, True = return output instead of return code.
  Returns:
    boolean, True = success, False = errors.
  """
  if input:
    input = subprocess.PIPE

  p = subprocess.Popen(cmd, shell=True, stdin=input, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
  p.wait()
  cmdoutput = p.stdout.read()

  if p.returncode:
    print(p.stderr.read())
  if output:
    return cmdoutput
  else:
    return not p.returncode


def GetSQLFromDict(dbtable, dict):
  """Convert a dictionary and produce sql for inserting into named table.

  Args:
    dbtable: string, name of database table.
    dict: dictionary where keys = fieldnames, and values are values to insert.
  Returns:
    string: mysql insert statement.
  """
  sql = 'REPLACE INTO ' + dbtable
  sql += ' ('
  sql += ', '.join(dict)
  sql += ') VALUES ('
  sql += ', '.join(map(DictString, dict))
  sql += ');'

  return sql


def DictString(key):
  return '%(' + str(key) + ')s'


def InsertToMySQL(constants, dbtable, fdict):
  """Insert values into MySQL from a dictionary.

  Args:
    constants: dictionary of values from processed YAML file.
    dbtable: string, database table to update.
    fdict: dictiony where key = field name, and value = value to insert.
  Returns:
    boolean: True = Success, False = error inserting into db.
  """
  sql = None
  status = False
  try:
    h = MySQLdb.connect(host=constants['REPORTHOST'], db=constants['DBNAME'],
                        user=constants['DBUSER'], passwd=constants['DBPASSWD'])
  except MySQLdb.OperationalError, e:
    print 'Error connecting to MySQL database: %s' % e
    raise MySQLdb.OperationalError(e)
  c = h.cursor()

  sql = GetSQLFromDict(dbtable, fdict)
  try:
    try:
      sql_result = c.execute(sql, fdict)
      if not sql_result:
        print 'Error inserting %s on %s' % (
            fdict['node'], constants['REPORTHOST'])
      else:
        h.commit()
        print 'Updated %s on %s' % (fdict['node'], constants['REPORTHOST'])
        status = True
    except MySQLdb.ProgrammingError, e:
      print 'Error updating row: %s' % e
  finally:
    h.close()

  return status


def SendToMySQL(constants, dbtable, fieldlist, valuelist):
  """Send values from list into fields and table passed in.

  Args:
    constants: dictionary of values from processed YAML file.
    dbtable: string, table to update in database.
    fieldlist: list, names of table fields.
    valuelist: list, values corresponding to field list.
  Returns:
    boolean: True = Success, False = error inserting into db.
  """

  status = False
  fields = ",".join(fieldlist)
  values = ",".join(valuelist)
  sql = 'INSERT INTO %s (%s) VALUES (%s)' % (dbtable, fields,values)

  if dbtable == 'machine_machine':
    query = "SELECT node FROM %s WHERE node = '%s'" % (dbtable, hostname)
  
  try:
    h = MySQLdb.connect(host=constants['REPORTHOST'], db=constants['DBNAME'],
                        user=constants['DBUSER'], passwd=constants['DBPASSWD'])
  except MySQLdb.OperationalError, e:
    print 'Error connecting to MySQL database: %s' % e
    raise MySQLdb.OperationalError(e)
  c = h.cursor()

  if dbtable == 'machine_machine':
    nodeindex = fieldlist.index('node')
    if nodeindex:
      hostname = valuelist[nodeindex]
      query = "SELECT node FROM %s WHERE node = '%s'" % (dbtable, hostname)
      result = c.execute(query) # Determine if host is in inventory.
      if result:
        # Need to change the lists and prepare for update statement.
        del fieldlist[nodeindex]
        del valuelist[nodeindex]
        fields_values = zip(fieldlist, valuelist)
        templist = []
        for field in fields_values:
          newfield = "=".join(field)
          templist.append(newfield)
        setvals = ",".join(templist)
        sql = 'UPDATE %s SET %s WHERE node = %s' % (dbtable, setvals, hostname)

  try:
    try:
      sql_result = c.execute(sql)
      if not sql_result:
        print 'Error handling %s on %s' % (hostname, constants['REPORTHOST'])
      else:
        h.commit()
        print 'Updated %s on %s' % (hostname, constants['REPORTHOST'])
        status = True
    except MySQLdb.ProgrammingError, e:
      print 'Error updating row: %s' % e
  finally:
    h.close()

  return status


def GetLTPHome(gtemp):
  """Get the LTP Home directory.

  Args:
    gtemp: string, path of working directory.
  Returns:
    string, pathname of LTPHOME.
  """

  print 'gtemp = %s' % gtemp
  ltpdir = os.path.join(gtemp, 'ltp-full*')
  tmpdir = glob.glob(ltpdir)
  return tmpdir[0]


def BuildLTP(constants):
  """Make, install, and configure the LTP test.

  Args:
    constants: dictionary of constant variables.
  Returns:
    string: home directory of LTP. None means there was an error.
  """

  make_cmds = ['./configure', 'sudo make', 'sudo make install']
  files_to_modify = ['testscripts/ltpstress.sh',
                     'runltp',
                    ]
  old_tmpbase = 'TMPBASE="/tmp"'
  new_tmpbase = 'TMPBASE="%s"' % constants['LTPHOME']
  ltphome = GetLTPHome(constants['ROOT'])
  os.chdir(ltphome)
  for cmd in make_cmds:
    status = ExecCall(cmd)
    if not status:
      break
  if status:
    # Change TMPBASE in the LTP test so it doesn't write its output file
    # in the /tmp directory. If the system happens to reboot before we get
    # the log file, we don't want to accidently lose this log file.
    rstatus = True
    # Later versions of LTP default to placing run files in /opt/ltp
    ltphome = '/opt/ltp'
    for f in files_to_modify:
      fpath = os.path.join('ltphome', f)
      if not ReplaceText(old_tmpbase, new_tmpbase, fpath):
        rstatus = False
    if not rstatus:
      print('TMPBASE not modified in the LTP.')

  if not status:
    ltphome = None
  
  return ltphome


def InstallPackage(pkg):
  """Install the simple stress program provided with Ubuntu.

  Args:
    pkg: name of package to install.
  Returns:
    boolean: true = success, false = errors.
  """

  cmd = 'sudo apt-get install -y %s' % pkg
  status = ExecCall(cmd)

  return status


def BuildBench(constants):
  """Make the UnixBench program.

  Args:
    constants: dictionary of constant variables.
  Returns:
    string: home directory of UnixBench. None means there was an error.
  """

  make_cmds = ['make',
               'javac runbench.java',
              ]
  bench_home = constants['BENCHHOME']
  
  # We need to copy in the java run file.
  dest = os.path.join(bench_home, constants['BENCHJAVA'])
  shutil.copyfile(constants['BENCHJAVA'], dest)

  # First remove any old reports, as UnixBench won't run if they are present.
  os.chdir(bench_home)
  try:
    reports = os.listdir('results')
  except IOError, e:
    print('Error accessing results directory\n%s', e)
  if reports:
    for f in reports:
      pathname = os.path.join('results', f)
      try:
        os.remove(pathname)
      except IOError, e:
        print('Error removing %s for UnixBench\n%s', pathname, e)


  for cmd in make_cmds:
    if not ExecCall(cmd):
      bench_home = None
      break

  return bench_home


def TarExtractTGZ(tgzfile, location):
  """Unzip and untar a .tgz compressed tarfile using python's tarfile.

  Args:
    tgzfile: string, filename of compressed tar file.
    location: string, directory to extract files into.
  Returns:
    boolean, True = success, False = failure.
  Assumes the tgz file is in location path.
  """

  status = True
  pathname = os.path.join(location, tgzfile)
  if not os.path.isfile(pathname):
    print('%s is not accessible!', pathname)
    status = 1
  else:
    try:
      os.chdir(location)
    except IOError, e:
      print('Error accessing %s\n%s', location, e)
      status = False
    try:
      tgz = tarfile.open(tgzfile, 'r:gz')
      for f in tgz:
        tgz.extract(f)
    except (tarfile.TarError, tarfile.ReadError, tarfile.CompressionError), e:
      print('Cannot extract files from %s', tgzfile)
      print(e)
      status = False
    tgz.close()

  return status


def ExtractTGZ(tgzfile, location):
  """Unzip and untar a .tgz compressed tarfile using the tar command.

  Args:
    tgzfile: string, the pathname of the .tgz file.
    location: string, the directory to extract files into.
  Returns:
    boolean, True = success, False = error.
  """

  status = True
  cmd = 'tar -xzvf %s' % tgzfile
  pathname = os.path.join(location, tgzfile)
  if not os.path.isfile(pathname):
    print('%s is not accessible!', pathname)
    status = False
  if not os.path.isdir(location):
    print('%s directory not present, cannot extract files to it!',
                 location)
    status = False
  else:
    try:
      os.chdir(location)
    except IOError, e:
      print 'Error accessing %s\n%s' % (location, e)
      status = False
    print 'Running %s' % cmd
    status = ExecCall(cmd)

  return status


def GetTypes(tree, toplevel):
  """Get the name of each type in yaml dictionary starting at toplevel.

  Args:
    tree: dictionary of parsed yaml file.
    toplevel: top level map to create list from.
  Returns:
    list of names.
  """

  return [item for item in tree[toplevel]]


def MakeDict(tree, toplevel, branch=None):
  """Create a dictionary of key value pairs from yaml tree.

  Args:
    tree: dictionary of parsed yaml file.
    toplevel: top level map to create dictionary from.
    branch: only return a dictionary from this branch. If branch is not
            defined we will return all key/value pairs from toplevel.
  Returns:
    dict of all bottom level key/value pairs in the toplevel tree section.
  """

  const_dict = {}
  if branch:
    for s in tree[toplevel][branch]:
      const_dict.update(s)
  else:
    for s in tree[toplevel]:
      for item in tree[toplevel][s]:
        const_dict.update(item)
  return const_dict


def MakeSCPList(tree, job, constants):
  """Make a list of packages to scp to remote systems.

  Args:
    tree: dictionary of parsed yaml file.
    job: string, type of job that will run on remote system.
    constants: dictionary of constructed constants.
  Returns:
    list of pathnames, 1 for each package needed for the job.
  """

  return [constants[k] for k in MakeDict(tree, 'testsuite', job)]


def GetConstants(const_dict, *ckeys):
  """Display keys and values for either ckeys or all constants.

  Args:
    const_dict: initialized dictionary of constants.
    ckeys: list of strings, keys of constants to show.
  Display the values of self.constants[*ckeys]. If no arguments are passed to
  ckeys, then display all values in self.constants. Write keys and values to
  a file for debugging.
  """

  constantfile = os.path.join(const_dict['ROOT'], 'constant.dict')
  fout = open(constantfile, 'w')
  print('\nShowing constants on host: %s', platform.node())

  if ckeys:
    constants = ckeys
  else:
    constants = const_dict
  try:
    for key in constants:
      print('%s: %s' % (key, constants[key]))
    try:
      fout.writelines(constants)
    except IOError, e:
      print(e)
      raise
  finally:
    fout.close()


def GetVersion():
  """Get kernel version and release string.

  Returns:
    dictionary of key/value pairs for simple version info.
  This method will grab the relevant versions of the kernel and Debian
  specific release strings.
  """
  versioninfo = {}

  cmds = {'kernel': 'uname -r',
          'arch': 'uname -m',
          'Distribution':
          "grep DISTRIB_ID /etc/lsb-release | awk -F'=' '{print $2}'",
          'Release':
          "grep DISTRIB_RELEASE /etc/lsb-release | awk -F'=' '{print $2}'",
          'Codename':
          "grep DISTRIB_CODENAME /etc/lsb-release | awk -F'=' '{print $2}'",
          'Description':
          "grep DESCRIPTION /etc/lsb-release | awk -F'=' '{print $2}'",
         }

  for cmd in cmds:
    p = subprocess.Popen(cmds[cmd], shell=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    versioninfo[cmd] = p.stdout.read()
    print(versioninfo[cmd])
  return versioninfo


def GetTimeString():
  """Return a string that represents the current time."""

  dt = datetime.datetime.now()
  t = dt.isoformat()
  time = t.split('.')
  return time[0]


def ReadFile(self, filename):
  """Read the contents of a file into lines, and return lines."""

  try:
    f = open(filename, 'r')
    lines = f.readlines()
  except IOError, e:
    self.logger.error('Error reading %s\n%s', filename, e)
    f.close()
  return lines
