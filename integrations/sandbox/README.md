# Sandbox integration boundary

The sandbox is the execution boundary for code, files and browser automation.

Defaults:
- bind service ports to loopback/private interfaces;
- require API authentication;
- do not expose VNC/Jupyter/VSCode publicly;
- use a pinned image release;
- review seccomp/AppArmor/capabilities;
- deny host filesystem mounts unless explicitly required;
- deny unrestricted network egress;
- inject secrets only for one operation;
- destroy the sandbox after untrusted work.

The upstream AIO Sandbox quickstart uses --security-opt seccomp=unconfined. That is not an acceptable production default for BUD.
