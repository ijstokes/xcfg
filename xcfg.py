#!/usr/bin/env python
"""
xcfg: XML swiss army knife configuration module and CLI

Head: $Head$
Id:   $Id: xcfg.py 384 2009-12-17 15:10:30Z ijstokes $

Ian Stokes-Rees, May 2008

Wouldn't you like to have a single configuration file format that is modular,
can be combined dynamically, and that can be used with multiple shells?

ConfigParser, the Python "standard" configuration manager had interface
shortcomings (including converting all keys to lowercase), so I've started a
mini-project that has been on my mind for years: a flexible XML-based
configuration language, an associated tool to provide Python APIs and also
CLI interface to integrate with shell environment variables.

Best described by example:

s1.xcfg:
<simple1
   foo="bar"
   zip="zap"
/>

s2.xcfg:
<simple2
   zip="bong"
   HOME="/tmp">
   <ping> pow </ping>
   <blort> wibble </blort>
</simple2>

# load these and print out the csh version:
xcfg load:s1.xcfg load:s2.xcfg sh=csh p

# load these in a different order, and output csh local variables
xcfg load:s2.xcfg load:s1.xcfg sh=csh  loc p

# now do it in bash
xcfg load:s1.xcfg load:s2.xcfg sh=bash p

# now black list blort (guesses shell syntax from current environment)
xcfg load:s1.xcfg load:s2.xcfg bl=blort p

# now combine the existing environment and use a white list
xcfg e load:s1.xcfg load:s2.xcfg  wl+=HOME wl+=zip wl+=USER wl+=PATH wl+=ping wl+=zip p

"How can I be one of the first people to experience, first hand, the marvels
of XConfig", you may be asking yourself... well, read on.

It is fairly smart and provided subversion keeps the execute bit set, it will
look after setting your PYTHONPATH for you.

# Try the interactive mode:
xcfg
# then type the commands one per line, but with spaces (e.g. load:s1.xcfg -> load : s1.xcfg)

# Help:
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
"""

import cmd
import sys
import optparse
import logging
import signal
import re
import os
import inspect
import logging
import string

try:
    import readline
except:
    pass # this just reduces some of the CLI features that are available

import UserDict

import xml.dom.minidom
from   xml.dom         import Node

(major, minor, patch, note, other) = sys.version_info

level_str = os.environ.get("PYLOG","DEBUG")

# Python 2.3 compatible dictionary replacement using %(varname)s
def j(str, d):
    # convert $FOO into %(FOO)s
    str_esc = re.sub(r"%","%%",str)
    # excape existing % characters
    str_mod = re.sub(r"\$([A-Za-z0-9_]+)", r"%(\1)s", str_esc) 
    result = str_mod % d
    return result

# Python 2.3 compatible globals+locals replacement using %(varname)s
def i(str):
    d = {}
    d.update(globals())
    d.update(locals())
    return j(str, d)

if (major >= 2) and (minor >= 4):
    logging.basicConfig(level=logging._levelNames[level_str], stream=sys.stderr, format="%(asctime)s:%(levelname)s:%(module)s:%(lineno)d:%(message)s", datefmt="%s")
    i = lambda _   : string.Template(_).safe_substitute(sys._getframe(1).f_globals, **sys._getframe(1).f_locals)
    j = lambda t,d : string.Template(t).safe_substitute(d)
else:
    from sets import Set as set
    logging.basicConfig()


class SimpleConfig:
    """ This is an empty holder class that will have config attributes added to it """
    pass

class INIConfig:
    """ This is an empty holder class that will have config attributes added to it """

    def __init__(self, filename=None):
        self.d = {}
        if filename != None:
            self.read(filename)

    def read(self, filename):
        " Parse an XConfig XML file and return an object with attributes and values "
        try:
            doc  = xml.dom.minidom.parse(filename)
        except:
            logging.error('read failed: %s' % filename)
            return
        root = doc.documentElement
        # Process children, collecting text and recursing into elements.
        # Assign as elements of this node.
        for section_node in root.childNodes:
            if section_node.nodeType == Node.ELEMENT_NODE:
                # convert all attributes on this to a dictionary for this section
                sec = {}
                idx = 0
                while idx < section_node.attributes.length:
                    attr = section_node.attributes.item(idx)
                    sec[attr.localName] = attr.value
                    idx += 1
                self.d[section_node.localName] = sec
        
class AdvancedConfig(UserDict.DictMixin):
    """ This is an empty holder class that will have config attributes added to it """

    def __getitem__(self, key):
        if hasattr(self, key):
            return getattr(self, key)
        else:
            raise KeyError(key)
    
    def __setitem__(self, key, item):
        self.keylist.add(key)
        setattr(self, key, item)
    
    def __delitem__(self, key):
        self.keylist.discard(key)
        delattr(self,key)
    
    def keys(self):
        return list(self.keylist)
    
    def __init__(self, filename=None):
        self.keylist = set()
        if filename != None:
            self.read(filename)

    def read(self, filename, mode="load"):
        " Parse an XConfig XML file and return an object with attributes and values "
        try:
            doc  = xml.dom.minidom.parse(filename)
        except:
            logging.error('read failed: %s' % filename)
            return

        root = doc.documentElement
        " This is just to solve the bootstrapping problem of the name for the root element "
        self.__NAME = root.localName
        self.parse_element(root, mode)
        self.convert_text()

    def xsetattr(self, attr, val, mode):
        """ if mode="load", then xsetattr=setattr
            if mode="merge", then xsetattr appends value with self.sep
        """
        if mode=="load":
            setattr(self, attr, val)
            self.keylist.add(attr)
        elif mode=="merge":
            if hasattr(self, attr):
                # FIXME: separator needs to be configurable
                setattr(self, attr, getattr(self, attr) + ":" + val.strip()) 
            else:
                setattr(self, attr, val)
                self.keylist.add(attr)
                
    def exp(self):
        """ Expand user and environment variables in all entries"""
        # FIXME: Cyclical references in environment variables will screw things
        # up, and unfortunately this is pretty common, e.g. PATH=$PATH:/foo/bar
        # TODO: implement exp:foo and exp:REGEX
        # expand system environment first in all dictionary entries
        for (k,v) in self.items():
            self[k] = os.path.expandvars(v)
            self[k] = os.path.expanduser(self[k])
        # expand config variables second (self-complete values from
        for (k,v) in self.items():
            self[k] = j(self[k],self)
        # second pass to substitute back in values for situations such as:
        # foo=xyz
        # first=$second/zip/zap
        # second=abc/$foo
        for (k,v) in self.items():
            self[k] = j(self[k],self)

    def s(self):
        """ Update environment from object entries """
        os.environ.update(self)


    def clean(self, sep):
        """ Go through all dictionary entries and remove duplicates in each
            entry based on separator """
        for (k,v) in self.items():
            final = []
            for p in self[k].split(sep):
                if not p in final:
                    final.append(p)
            self[k] = sep.join(final)

    def parse_element(self, node, mode):
        """ An element is referred to by its local name.  It could have attributes,
            text, and child elements.  If it has non-whitespace text content, then
            the value of the element is a string and any attributes or elements
            are ignored (a warning is printed if the logging level is >= WARN).
            Otherwise attributes are assigned first and then elements.  This means
            an element with a child element and attribute having the same name:
                <foo bar="abc">
                    <bar> 42 </bar>
                </foo>
            will end up with the child element value overwriting the attribute.
            In this example, foo.bar == 42 (not "abc").
        """
        text_list   = []
        child_dict  = {}
        hasText     = False
        hasElements = False
        hasAttribs  = False
        content_cnt = 0

        # Process children, collecting text and recursing into elements.
        # Assign as elements of this node.
        for n in node.childNodes:
            if n.nodeType == Node.ELEMENT_NODE:
                hasElements = True
                if mode=="load":
                    cfg = AdvancedConfig()
                    setattr(self, n.localName, cfg)
                elif mode=="merge":
                    if hasattr(self,n.localName):   # already exists
                        cfg = self.d[n.localName]
                    else:                           # same as load
                        cfg = AdvancedConfig()
                        setattr(self, n.localName, cfg)
	            cfg.parse_element(n, mode)
                        
            elif n.nodeType == Node.TEXT_NODE:
                hasText = True
                text_list.append(n.nodeValue.strip())

        if node.attributes.length > 0:
            hasAttribs = True

        if hasText:     content_cnt += 1
        if hasElements: content_cnt += 1
        if hasAttribs:  content_cnt += 1

        if content_cnt > 1:
            logging.warn("More than 1 type of content in node [%s]" % node.localName)

        text = " ".join(text_list)
        text = text.strip()
        if len(text) > 0: # there is some text, so replace this object with the string
            self.xsetattr("__TEXT", text, mode)
            if hasElements or hasAttribs:
                logging.warn("Node [%s] has text content. Using this as node value, ignoring elements and attributes" % node.localName)
            return
        else: # there is no text, so add attributes and then elements
            idx = 0 # unfortunately node.attributes is not iterable, so we use a while loop
            while idx < node.attributes.length:
                attr = node.attributes.item(idx)
                self.xsetattr(attr.localName, attr.value, mode)
                idx += 1

            for k in child_dict.keys():
                self.xsetattr(k, child_dict[k], mode)

    def axpath(self,path):
        """ Almost XPath query.  Splits on slashes to query AdvancedConfig object.
            AXPath doesn't support SCS/predicates, and doesn't know anything about
            axes, namespaces, or attribute identifiers (attributes get munged into
            the / path syntax).
        """
        path   = path.strip("/") # remove leading and trailing slashes
        parts  = path.split("/")
        result = ""
        if   len(parts) == 0:
            result = self
        elif len(parts) == 1:
            result = getattr(self,parts[0])
        elif len(parts) > 1:
            result = AdvancedConfig.axpath(getattr(self, parts[0]), "/".join(parts[1:]))

        return result

    def convert_text(self):
        """ Converts AdvancedConfig attributes with __TEXT into a simple
            string attribute.  This is a horrible hack because I can't
            figure out how to "in place" convert a text-only AdvancedConfig
            object into a string (self = text doesn't work).
        """
        for slot in dir(self):
            attr = getattr(self,slot)
            attr_type = type(attr).__name__
            if attr_type == "instance":
                if "__TEXT" in dir(attr):
                    setattr(self, slot, getattr(attr, "__TEXT"))
                else:
                    AdvancedConfig.convert_text(attr)

    def todict(self):
        """ Munge (technical term) XConfig file into a single dictionary.
            Creates an AdvancedConfig object and then traverses it in a
            quasi-depth first fashion (siblings are processed in a random
            order) assigning all leaf nodes (attribute/string-value) to
            dictionary entries.  Anything containing "__" will be ignored.

            Basically, if you don't repeat node names anywhere, you'll be
            fine. If you do, your resulting dictionary may not have the
            values you expect.
        """
        d = {}

        for slot in dir(self):
            if slot.find("__") >= 0: continue # skip attributes containing "__"
            attr = getattr(self,slot)
            attr_type = type(attr).__name__
            if attr_type == "str" or attr_type == "unicode":
                d[slot] = attr
            elif attr_type == "instance":
                d.update(AdvancedConfig.todict(getattr(self, slot)))

        return d
    
    def toFile(self, filename):
        impl = xml.dom.minidom.getDOMImplementation()

        if hasattr(self, "__NAME"):
            name = self.__NAME
        else:
            name = "xconfig"
        
        xcfg_dom  = impl.createDocument(None, name, None)
        xcfg_root = xcfg_dom.documentElement
        for entry in dir(self):
            if entry.startswith("__"):
                continue
            attr = getattr(self, entry)
            if type(attr) == type("abc"):
                attr = attr.strip()
                if attr.find("\n") >= 0:
                    ele = xcfg_dom.createElement(entry)
                    text = xcfg_dom.createTextNode("\n%s\n" % attr)
                    ele.appendChild(text)
                    xcfg_root.appendChild(ele)
                else:
                    new_attr = xcfg_dom.createAttribute(entry)
                    xcfg_root.setAttributeNode(new_attr)
                    xcfg_root.setAttribute(entry, attr)
            elif hasattr(attr, "items"):
                ele = xcfg_dom.createElement(entry)
                xcfg_root.appendChild(ele)
                for (k,v) in attr.items():
                    new_attr = xcfg_dom.createAttribute(k)
                    ele.setAttributeNode(new_attr)
                    ele.setAttribute(k, v)
        
        out_fh = open(filename, "w")
        out_fh.write(xcfg_root.toprettyxml(indent="  "))
        out_fh.write("\n<!-- \n# vim:set sw=20 ts=20 : -->")
        out_fh.close()

def parsed(filename):
    " Parse an XConfig XML file and return a dictionary of name/value pairs "
    xcfg_dict   = {}
    doc         = xml.dom.minidom.parse(filename)
    root        = doc.documentElement
    idx = 0
    while idx < root.attributes.length:
        attr = root.attributes.item(idx)
        xcfg_dict[attr.localName] = attr.value
        idx += 1

    return xcfg_dict

def parseo(filename):
    " Parse an XConfig XML file and return an object with attributes and values "
    xcfg_obj    = SimpleConfig()
    doc         = xml.dom.minidom.parse(filename)
    root        = doc.documentElement
    idx = 0
    while idx < root.attributes.length:
        attr = root.attributes.item(idx)
        eval("xcfg_obj.%s = %s" % (attr.localName, attr.value))
        idx += 1

    return xcfg_obj

def attr2dict(filename):
    """ Parse an XConfig XML file and return a dictionary of name/value pairs
        from the attributes on the document element.
    """
    xcfg_dict   = {}
    doc         = xml.dom.minidom.parse(filename)
    root        = doc.documentElement
    idx = 0
    while idx < root.attributes.length:
        attr = root.attributes.item(idx)
        xcfg_dict[attr.localName] = attr.value
        idx += 1

    return xcfg_dict

def xcfg2dict(filename):
    xcfg = AdvancedConfig(filename)
    return xcfg.todict()

class XcfgCLI(cmd.Cmd):
    """
 foo=bar     : set foo to value bar
 foo+=bar    : append  bar onto foo
 foo++=bar   : prepend bar onto foo
 foo-=bar    : remove all occurances of bar from foo

TODO: Not yet implemented
 foo+=*bar   : append  bar onto foo, *=[:_/\\;]
 foo++=*bar  : prepend bar onto foo, *=[:_/\\;]
 foo-=*bar   : remove all occurances of distinct bar from foo, *=[:_/\\;]
    """

    COMMANDS        = "e s p pp load merge clean exp wl bl arch sh env loc reset help exit".split()
    SHELL_DEFAULT   = "bash"

    def do_e(self, line=""):
        """ e           : load os environment
 e:foo,bar   : load os environment variables foo and bar
"""
        match = re.search("\s*(?P<sep>[-+=:\\;]{0,4})\s*(?P<last>.*)\s*", line)
        sep   = match.group("sep")
        last  = match.group("last")

        # these have screwy escape codes or are typically multi-line
        for bad in ['TERMCAP']:
            if os.environ.has_key(bad): 
                del os.environ[bad]

        if sep == "":
            self.xcfg.update(os.environ)
        elif sep == ":":
            for v in last.split(","):
                v = v.strip()
                try:
                    self.xcfg[v] = os.environ[v]
                except:
                    logging.debug("%s not found in environment" % v)

    def do_s(self, line=""):
        """ s           : set os environment """
        self.xcfg.s()

    def do_p(self, line=""):
        """ p           : print xcfg state (shell compatible syntax)
 p:REGEX     : print xcfg state for keys that match REGEX (shell compatible syntax)
"""
        (pre, mid, wrap) = self.sh_syntax()

        search=""
        if line.find(":") >= 0:
            parts  = line.split(":")
            search = parts[1].strip()

        keys = self.xcfg.keys()
        keys.sort()
        for k in keys:
            if line != "": # check against explicit REGEX
                match = re.search(search,k)
                if match is None:
                    continue
            else: # check against black and white lists
                if (len(self.bl) > 0) and (k in self.bl):
                    continue # skip this key, found in black list
                if (len(self.wl) > 0) and not (k in self.wl): # only output entries that are in white list, skip otherwise
                    continue # skip this key, not in white list
            v = self.xcfg[k]
            if (v.find(" ") >= 0) or (v.find("=") >= 0):
                w = wrap
            else:
                w = ""
            print "%s%s%s%s%s%s" % (pre, k, mid, w, v, w)

    def do_pp(self, line=""):
        """ pp          : pretty print xcfg state (shell compatible syntax) """
        self.do_p(line)

    def do_load(self, line=""):
        """ load:file   : load XConfig file """
        parts = line.split()
        self.xcfg.read(parts[1])
        
    def do_merge(self, line=""):
        """ merge:file   : merge XConfig file """
        parts       = line.split()
        self.xcfg.read(parts[1], mode="merge")

    def do_wl(self, line=""):
        """ wl=foo      : white list foo for output 
 wl+=foo     : append foo to white list
 wl:file     : load white list from file
"""
        match = re.search("\s*(?P<sep>[-+=:\\;]{0,4})\s*(?P<last>.*)\s*", line)
        sep   = match.group("sep")
        last  = match.group("last")
        if sep == "":
            pass
        elif sep == "=":
            self.wl = [last]
        elif sep == "+=":
            self.wl.append(last)

    def do_bl(self, line=""):
        """ bl=foo      : black list foo from output
 bl+=foo     : append foo to black list
 bl:file     : load black list from file
"""
        match = re.search("\s*(?P<sep>[-+=:\\;]{0,4})\s*(?P<last>.*)\s*", line)
        sep   = match.group("sep")
        last  = match.group("last")
        if sep == "":
            pass
        elif sep == "=":
            self.bl = [last]
        elif sep == "+=":
            self.bl.append(last)
        pass

    def do_exp(self, line=""):
        """ exp         : expand all environment variables (e.g. $FOO and ~)
TODO
 exp:foo     : expand environment variable foo
 exp:REGEX   : expand all environment variables that match REGEX
"""
        self.xcfg.exp()

    def do_clean(self, line=""):
        """ clean       : clean all environment variables (single occurance of each item)
TODO
 clean:foo   : clean environment variable foo
 clean:REGEX : clean all environment variables that match REGEX
"""
        self.xcfg.clean(self.sep)

    def do_arch(self, line=""):
        """ arch        : set ARCH based on uname """
        arch  = "i386" # default
        opsys = os.uname()[0]   # e.g. Linux, Darwin, etc.
        proc  = os.uname()[-1]  # e.g. x86_64, i386, i686, ppc, etc.
        if opsys == "Linux":
            if proc == "x86_64":
                arch = "x86_64"
            else:
                arch = "i386"
        if opsys == "Darwin":
            if proc == "i386":
                arch = "osx_intel"
            else:
                arch = "osx_ppc"
        self.xcfg["ARCH"] = arch

    def do_sh(self, line=""):
        """ sh=shell    : set shell syntax to shell """
        parts       = line.split("=")
        self.shell  = parts[1].strip()

    def do_sep(self, line=""):
        """ sep=[:;,]    : set separator for lists"""
        parts       = line.split("=")
        self.sep    = parts[1].strip()

    def do_env(self, line=""):
        """ env         : use environment export [default] """
        self.EXPORT_ENV = True

    def do_loc(self, line=""):
        """ loc         : use local shell export """
        self.EXPORT_ENV = False

    def do_reset(self, line=""):
        """ reset       : reset internal state (dict and xcfg) """
        self.d          = {} # dictionary of entries
        self.wl         = [] # white list of entries to print
        self.bl         = [] # black list of entries to suppress
        self.sep        = ":"
        self.xcfg       = AdvancedConfig()
        self.EXPORT_ENV = True

    def do_exit(self, line=""):
        """ exit        : exit xcfg """
        sys.exit(0)

    def do_help(self, cmd):
        """ help        : print help """
        funcname = "do_%s" % cmd
        if funcname in dir(self):
            func = getattr(self, funcname)
            if hasattr(func, "__doc__"):
                print getattr(func, "__doc__")
        else:
            for cmd in self.COMMANDS:
                attr = "do_%s" % cmd
                if not attr.startswith("do_"): continue
                func = getattr(self, attr)
                if hasattr(func, "__doc__"):
                    print getattr(func, "__doc__")
            print self.__doc__

    def default(self, line):
        match = re.search("(?P<first>\w+)\s*(?P<sep>[-+=:\\;]{0,4})\s*(?P<last>.*)\s*", line)
        first = match.group("first")
        sep   = match.group("sep")
        last  = match.group("last")
        if sep == "":
            pass
        elif sep == "=":
            self.xcfg[first] = last
        elif sep == "+=":
            if not self.xcfg.has_key(first):
                self.xcfg[first] = ""
            self.xcfg[first] += self.sep + last
        elif sep == "++=":
            if not self.xcfg.has_key(first):
                self.xcfg[first] = ""
            self.xcfg[first] = last + self.sep + self.xcfg[first]
        else:
            logging.debug("Invalid syntax: [%s]" % line)
            pass

    def sh_syntax(self):
        pre  = ""
        mid  = "="
        wrap = ""
        if hasattr(self, "shell"):
            shell = self.shell
        elif os.environ.has_key("SHELL"):
            shell_path = os.environ["SHELL"]
            if shell_path.find("csh") > 0:
                shell = "csh"
            else:
                shell = self.SHELL_DEFAULT
        else:
            shell = self.SHELL_DEFAULT
        
        wrap = '"'
        if shell == "csh":
            if self.EXPORT_ENV:
                pre="setenv "
                mid=" "
            else:
                pre="set "
                mid="="
        else: # default to bash syntax
            mid="="
            if self.EXPORT_ENV:
                pre="export "
            else:
                pre=""

        return (pre, mid, wrap)

    def __init__(self):
        cmd.Cmd.__init__(self)
        self.do_reset()
        

class SignalHandler:
    def __init__(self):
        signal.signal(signal.SIGINT, self)
        return
 
    def __call__(self, signame, sf):
        print ""
        sys.exit(0)
        return
 
if __name__ == '__main__':

    bh          = SignalHandler()
    cli         = XcfgCLI()
    cli.prompt  = "xcfg: "

    if len(sys.argv) > 1:
        found_file = False
        cfg_fp = sys.argv[1]
        while os.path.isfile(cfg_fp):
            found_file = True
            cli.xcfg.read(cfg_fp)
            del(sys.argv[1]) # remove it from the arguments list
            try:
                cfg_fp = sys.argv[1]
            except:
                break

        if len(sys.argv) > 1: # there are still commands left, so continue with them
            for part in sys.argv[1:]:
                match = re.search("(?P<first>\w+)(?P<sep>[-+=:\\;]{0,4})(?P<last>.*)", part)
                first = match.group("first")
                sep   = match.group("sep")
                last  = match.group("last")
                cli.onecmd("%s %s %s" % (first, sep, last))
        else: # it was just a list of files to read in
            if found_file:
                cli.onecmd("arch")
                cli.onecmd("exp")
                cli.onecmd("clean")
                cli.onecmd("p")
            else: # nothing left, and no files found, so just print help
                cli.onecmd("help")
    else:
        print "Type help for a list of commands"
        cli.cmdloop()                             
