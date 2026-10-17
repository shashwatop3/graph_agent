"""Ring Fire: the benchmark game, as a pack the console can load.

    sim/          the fire engine, message network, imposters and oracle (imports nothing)
    adapter.py    what a fire belief means: predicates, parsers, the evidence rule, the role card
    benchmark/    the original game loop, the memory systems (graph and baselines), scoring, sweeps
    pack.py       the game on the frame: the world node, the ring network, the team file
    standin.py    a scripted stand-in agent (the console's free demo)
    console.py    what the console needs: templates, options, the fields lens
    viewer/       the Ring Fire log viewers (cascade, the S12 replay page) and design drafts
"""
