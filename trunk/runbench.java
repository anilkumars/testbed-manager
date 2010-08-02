// Copyright 2010 Google Inc. All Rights Reserved.



/**
 *
 * @author kdlucas@google.com (Kelly Lucas)
 * This program will drive the UnixBench program. The problem I ran into when
 * trying to drive the UnixBench program from Python, is that I would get
 * broken pipes during the pipe base context switching tests. Using this Java
 * program to drive UnixBench solves the issue.
 */

import java.io.*;
import java.util.*;


class StreamGobbler extends Thread {

  InputStream is;
  String type;

  StreamGobbler(InputStream is, String type) {
    this.is = is;
    this.type = type;
  }

  public void run() {
    try {
      InputStreamReader isr = new InputStreamReader(is);
      BufferedReader br = new BufferedReader(isr);
      String line=null;
      while((line = br.readLine()) != null)
        System.out.println(type + ">" + line);
    } catch (IOException ioe) {
        ioe.printStackTrace();
        }
  }
}

public class runbench extends Thread {

  static void runbench() {
    try {
      Runtime runtime = Runtime.getRuntime();
      String[] args = new String[] {"bash", "-c", "./Run -c 16"};
      Process p = runtime.exec(args);
      StreamGobbler errorGobbler = new StreamGobbler(p.getErrorStream(), "ERROR");
      StreamGobbler outputGobbler = new StreamGobbler(p.getInputStream(), "OUTPUT");
      errorGobbler.start();
      outputGobbler.start();
      int exitVal = p.waitFor();
      System.out.println("ExitValue: " + exitVal);
    }
  catch (Throwable t) {
    t.printStackTrace();
    }
  }

  public static void main(String[] args) throws IOException {
    runbench();
  }

}
