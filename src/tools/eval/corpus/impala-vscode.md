---
title: "Impala in VS Code"
space: "DATA"
source_file: "impala-vscode.html"
---

##

## Introduction

VSCode classifies itself as a code editor.  Thus, VSCode itself does not do the heavy lifting of compiling/linting/testing/etc.  Instead, it calls out to external command line utilities and language servers to do the bulk of the heavy lifting.  VSCode leverages the [language server protocol](https://code.visualstudio.com/api/language-extensions/language-server-extension-guide) which enables standardized communication with any language servers that support the protocol.  These design choices lead to VSCode being a powerful remote development environment but does require a higher-than-average initial setup time.

For developers wishing to utilize a remote Redhat/Ubuntu development environment, VSCode enables such an environment.  In a remote development setup, the Impala codebase resides on a remote Linux machine accessible via SSH.  The remote machine is where Impala is compiled, tested, and ran.  The VSCode backend server also runs on the remote machine.  A local machine is where the VSCode editor's front-end runs.  The protocol that VSCode uses for communication between its frontend and backend is very lightweight and thus provides a better experience versus other remote development solutions such as remote desktop access or network file sharing.

## Setup

Prerequisites:  Successful completion of [Bootstrapping an Impala Development Environment From Scratch](/confluence/display/IMPALA/Bootstrapping+an+Impala+Development+Environment+From+Scratch).

To use VSCode for Impala development (either local or remote):

1.  [Install VSCode](https://code.visualstudio.com/docs/setup/setup-overview).  If setting up a remote development environment, install VSCode on both the local and remote machines.
2.  If setting up a remote development environment, run VSCode on the local machine and connect it to the remote machine.
    1.  Set up the remote development machine as a Host in the ~/.ssh/config file on the local machine.
    2.  Install the Extension Remote-SSH (extension id: ms-vscode-remote.remote-ssh).
    3.  Open the [Command Palette](https://code.visualstudio.com/docs/getstarted/userinterface#_command-palette) and run the Remote-SSH: Connect to Host command.
    4.  Select the SSH Host corresponding to the remote development machine (from step 2a).  A new VSCode window will open.
3.  Install the following Extensions.  When setting up a remote development environment, ensure it is being installed on the remote development environment by verifying the extension's install button has a title starting with "Install in SSH".
    1.  C/C++ Extension Pack (extension id: ms-vscode.cpptools-extension-pack)
    2.  Extension Pack for Java (extension id: vscjava.vscode-java-pack)
    3.  Python (extension id: ms-python.python)
4.  Add the folders of each of the projects under development (e.g. "fe", "be", "shell", "tests", "bin").
5.  Follow the VSCode prompts to set up each project.
6.  The cmake extension needs to be configured with C/C++ compilers.  When prompted to "Select a Kit", this is asking which compilers to use when building Impala.
    1.  To use the toolchain's gcc compiler, choose "\[Scan recursively for kits in specified directories (max depth:5)\].
        1.  ![](/confluence/download/attachments/235837535/cmake-select-kit.png?version=2&modificationDate=1755702240000&api=v2)

    2.  Then, select the "toolchain/toolchain-packages-gcc10.4.0" folder.
        1.  ![](/confluence/download/attachments/235837535/cmake-choose-folder.png?version=1&modificationDate=1755702520000&api=v2)

    3.  Finally, when prompted again to "Select a Kit", choose the GCC compiler from the toolchain directory.

        1.  ![](/confluence/download/attachments/235837535/cmake-select-kits-after.png?version=4&modificationDate=1755702772000&api=v2)

## Front-end Development using VSCode

### Setup

Following the instructions in the general setup section will result in all necessary extensions getting installed.

### Run/Debug Unit Tests

1.  Navigate to the Run and Debug view (left side toolbar).

2.  Click the Gear icon to open the launch.json file or click the "create a launch.json file" link if that link is visible.

3.  Add the following configuration:

    ``` java
    {
      "type": "java",
      "name": "FE Test Attach",
      "request": "attach",
      "hostName": "localhost",
      "port": 8000,
      "projectName": "impala-frontend"
    }
    ```

4.  Follow the steps in [Debugging front-end test](/confluence/display/IMPALA/Debugging+front-end+test) to launch a JVM that will listen for a debugger connection before continuing.

5.  In VSCode, navigate to the Run and Debug view again and launch "FE Test Attach (fe)".

### Remote Debug Frontend

The frontend JVM opens a port for remote debugging starting with port 30000 for coordinator 0 and incrementing by 1 for each coordinator (30001 for coordinator 1, 30002 for coordinator 2, etc).  Thus, the best way to debug the front end is to start a single node Impala cluster thus ensuring the frontend remote debugging port will be 30000.

Then, set up VSCode as follows:

1.  Navigate to the Run and Debug view (left side toolbar).

2.  Click the Gear icon to open the launch.json file or click the "create a launch.json file" link if that link is visible.

3.  Add the following configuration:

    ``` java
        {
          "type": "java",
          "name": "Coordinator 0 FE Debug",
          "request": "attach",
          "hostName": "localhost",
          "port": 30000,
          "projectName": "impala-frontend"
        }
    ```

4.  Set breakpoints as needed in the frontend java code.

5.  In the left-side activity bar, click "Run and Debug".

6.  Select "Coordinator 0 FE Debug" from the drop-down.

7.  Click the "Start Debugging" button.  When queries are submitted, code execution will pause on the breakpoints.

## Using Dev Container (Developing Inside Docker Container)

1.  Install [Visual Studio Code](https://code.visualstudio.com/download).
2.  Install [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) extension.
3.  Open Visual Studio Code from \$IMPALA_HOME, i.e. code \$IMPALA_HOME
4.  Visual Studio will recognize .devcontainer configuration and will prompt to open in a container. Choose to open in a container. This process will take quite some time since it will need to run the bootstrap_development.sh.
5.  Visual Studio will install the necessary extensions needed for Impala development. When it prompts to install clangd, choose yes. That will provide code completion for C++.

For more information about Dev Container, refer to [this doc](https://code.visualstudio.com/docs/devcontainers/containers).
