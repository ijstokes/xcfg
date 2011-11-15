xcfg: XML swiss army knife configuration module and CLI
=======================================================

Ian Stokes-Rees, May 2008

Wouldn't you like to have a single configuration file format that is modular,
can be combined dynamically, and that can be used with multiple shells?

ConfigParser, the Python "standard" configuration manager had interface
shortcomings (including converting all keys to lowercase), so I've started a
mini-project that has been on my mind for years: a flexible XML-based
configuration language, an associated tool to provide Python APIs and also
CLI interface to integrate with shell environment variables.

Best described by example:

    :::s1.xcfg:
    <simple1
       foo="bar"
       zip="zap"
    />

    :::s2.xcfg:
    <simple2
       zip="bong"
       HOME="/tmp">
       <ping> pow </ping>
       <blort> wibble </blort>
    </simple2>

load these and print out the csh version:

    xcfg load:s1.xcfg load:s2.xcfg sh=csh p

load these in a different order, and output csh local variables

    xcfg load:s2.xcfg load:s1.xcfg sh=csh  loc p

now do it in bash

    xcfg load:s1.xcfg load:s2.xcfg sh=bash p

now black list blort (guesses shell syntax from current environment)

    xcfg load:s1.xcfg load:s2.xcfg bl=blort p

now combine the existing environment and use a white list

    xcfg e load:s1.xcfg load:s2.xcfg  wl+=HOME wl+=zip wl+=USER wl+=PATH wl+=ping wl+=zip p

"How can I be one of the first people to experience, first hand, the marvels
of xcfg?", you may be asking yourself... well, read on.

It is fairly smart and provided subversion keeps the execute bit set, it will
look after setting your PYTHONPATH for you.

Try the interactive mode:

    xcfg

then type the commands one per line, but with spaces (e.g. load:s1.xcfg -> load : s1.xcfg)

Help:

    xcfg help

Some more comments:

Basically any valid XML can be used for the configuration file (namespaces are
dropped, and elements with text value and also attributes ignore the
attributes), and you then have access to structured objects (adv.blort or
adv.foo), or a dictionary with name value pairs for all leaf nodes (foo, zip,
blort).

The shell environment tool does three things: facilitates editing environment
variables; transforms environment variable settings between bash and tcsh
syntax (also understands difference between local variables, and exported
environment variables); and enables combining in arbitrary order settings from
files, command line, and environment and outputting some or all of these.
