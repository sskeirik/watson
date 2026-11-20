![logo Watson](img/logo-watson-600px.png)

## Overview

> This is a personal fork of [Watson](https://github.com/TailorDev/Watson) by
> [TailorDev](https://github.com/TailorDev) and its contributors, to whom all
> credit for the original tool belongs. The fork's repository is
> [sskeirik/watson](https://github.com/sskeirik/watson).

Watson is here to help you monitor your time. You want to know how
much time you are spending on your projects? You want to generate a nice
report for your client? Watson is here for you.

Tell Watson when you start working on a task with the `start` command.
Then, when you are done, stop the timer with the `stop`
command. This will create what we call a **frame**. That's pretty much
everything you need to know to start using Watson.

Each frame consists of the name of a project and some tags. Your tags
can be shared across projects and can be used to generate detailed
reports.

Watson stores everything on your computer, but you can go wild and
upload to your own [crick server](https://github.com/TailorDev/crick)
via the `sync` command to store your sessions remotely and share them
with your colleagues.

![screenshot](img/screenshot.png)

## Installation

This fork requires Python 3.12+ and runs on Windows, macOS and Linux. Install
it with [uv](https://docs.astral.sh/uv/):

```bash
$ uv tool install git+https://github.com/sskeirik/watson
```

The packages on PyPI, Homebrew and the AUR are for the original Watson, not
this fork.

If the `watson` command is not available, you need to add `~/.local/bin/` to your `PATH`. If your terminal is Bash, you can do this by running:

```bash
$ echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc  # Add ~/.local/bin/ to your .bashrc PATH
```

and restarting your terminal session or sourcing the `.bashrc`:

```bash
$ source ~/.bashrc  # Reload your .bashrc
```

### Development version

The latest development version can be installed using the following commands:

```bash
$ git clone https://github.com/sskeirik/watson.git
$ cd watson/
$ uv tool install -e .
```

### Command line completion

#### Bash


If you use a Bash-compatible shell, you can install the `watson.completion` file from the source distribution as `/etc/bash.completion.d/watson` - or wherever your distribution keeps the Bash completion configuration files. After you restart your shell, you can then just type `watson` on your command line and then hit `TAB` to see all available commands. Depending on your input, it completes `watson` commands, command options, projects, tags and frame IDs.

#### ZSH

If you use zsh, copy the file `watson.zsh-completion` somewhere in your
`fpath` as `_watson`. For example, you can put it in
`/usr/local/share/zsh/site-functions`:

    cp watson.zsh-completion /usr/local/share/zsh/site-functions/_watson

Make sure that your .zshrc enables compinit:

    autoload -Uz compinit && compinit

#### Fish

If you use fish, you can copy or symlink the file `watson.fish` from the source distribution to `~/.config/fish/completions/watson.fish`.
You may need to make the completions directory as it is not created by default.

Once this is done, re-source your fish config:
  `source ~/.config/fish/config.fish`

You will now have command completion for fish, including the completion of known projects, tags, and frames.



## Getting started

Now that `watson` is installed on your system, let's start tracking your activity:

```bash
$ watson start world-domination +cats
```

With this command, you have started a new **frame** for the *world-domination* project with the *cat* tag. Time is running. Now, you need to work on your project. Let's do this. Now.

![Working cat](img/working-cat.gif){: width="400px" }

Welcome back! Now that your world domination plan has been set up, let's stop time tracking via:

```bash
$ watson stop
Project world-domination [cat] started 34 minutes ago (id: 166d1fb)
```

To list all available commands, either [explore the commands documentation](user-guide/commands.md) or use:

```bash
$ watson help
```

We hope you will enjoy Watson!
