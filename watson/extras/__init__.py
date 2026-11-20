"""Work-hours features built on top of Watson's core.

- ``schedule``: the standard work schedule and the optional alternate one
- ``policies``: forgotten-timer triggers (pure; no I/O)
- ``handlers``: what a policy does when it fires (toast, autostop, prompt)
- ``watch``: one evaluation pass, run periodically by the OS scheduler
- ``review``: correcting flagged frames, at the next ``watson start`` or
  through ``watson review``
- ``commands``: the click commands, registered on Watson's CLI group
"""
