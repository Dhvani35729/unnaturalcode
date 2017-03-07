#!/usr/bin/python
#    Copyright 2013, 2014 Joshua Charles Campbell
#
#    This file is part of UnnaturalCode.
#    
#    UnnaturalCode is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    UnnaturalCode is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with UnnaturalCode.  If not, see <http://www.gnu.org/licenses/>.

from unnaturalcode.ucUtil import *
from unnaturalcode.unnaturalCode import *
from unnaturalcode.pythonSource import *
from unnaturalcode.mitlmCorpus import *
from unnaturalcode.sourceModel import *

from logging import debug, info, warning, error
import logging
from random import randint
from os import path

import csv
import runpy
import sys, traceback
from shutil import copyfile
from tempfile import mkstemp, mkdtemp
import os, re, site

from multiprocessing import Process, Queue
try:
  from Queue import Empty
except ImportError:
  from queue import Empty
from unnaturalcode import flexibleTokenize

import pdb

virtualEnvActivate = os.getenv("VIRTUALENV_ACTIVATE", None)
# wow, this is actually how virtualenv does it...
virtualEnvBase = os.path.basename(os.path.basename(virtualEnvActivate))
virtualEnvSite = os.path.join(virtualEnvBase, 'lib', 'python%s' % sys.version[:3], 'site-packages')


nonWord = re.compile('\\W+')
beginsWithWhitespace = re.compile('^\\w')
numeric = re.compile('[0-9]')
punct = re.compile('[~!@#$%^%&*(){}<>.,;\\[\\]`/\\\=\\-+]')
funny = re.compile(flexibleTokenize.Funny)
name = re.compile(flexibleTokenize.Name)

class HaltingError(Exception):
  def __init__(self, value):
    self.value = value
  def __str__(self):
    return repr(self.value)

def runFile(q,path,mode):
    if not virtualEnvActivate is None:
      if sys.version_info >= (3,0):
        exec(compile(open(virtualEnvActivate, "rb").read(), virtualEnvActivate, 'exec'), dict(__file__=virtualEnvActivate))
      else:
        execfile(virtualEnvActivate, dict(__file__=virtualEnvActivate))
    parent = path
    runit = None
    while len(parent) > 1:
        parent = os.path.dirname(parent)
        sys.path = sys.path + [parent]
        if mode == 'module':
            moduleSite = ""
            #info("Path: %s" % path)
            for s in sys.path:
                if s in path:
                    if ('site-packages' in path and
                        (not 'site-packages' in os.path.basename(s))):
                        continue
                    if len(s) > len(moduleSite):
                        moduleSite = s
                        break
            #info("Python path: %s" % moduleSite)
            relpath = os.path.relpath(path, moduleSite)
            #info("Relative path: %s" % relpath)
            components = relpath.split(os.path.sep)
            components[-1] = components[-1].replace(".py", "", 1)
            module = ".".join(components)
            #info("Module name: %s" % module)
            runit = lambda: runpy.run_module(module)
        elif mode == 'script':
            runit = lambda: runpy.run_path(path)
        elif mode == 'module_indir':
            moduledir = os.path.dirname(path)
            filename = os.path.basename(path)
            os.chdir(moduledir)
            runit = lambda: runpy.run_path(filename)
        else:
            raise ValueError("Mode not recognized?") 
    old_stdout = os.dup(sys.stdout.fileno())
    old_stderr = os.dup(sys.stderr.fileno())
    old_stdin = os.dup(sys.stdin.fileno())
    devnull = os.open('/dev/null', os.O_RDWR)
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    os.dup2(devnull, sys.stdin.fileno())
    try:
        runit()
    except SyntaxError as se:
        os.dup2(old_stdout, sys.stdout.fileno())
        os.dup2(old_stderr, sys.stderr.fileno())
        os.dup2(old_stdin, sys.stdin.fileno())
        ei = sys.exc_info();
        info("run_path exception:", exc_info=ei)
        eip = (ei[0], str(ei[1]), traceback.extract_tb(ei[2]))
        try:
          eip[2].append(ei[1][1])
        except IndexError:
          eip[2].append((se.filename, se.lineno, None, None))
        q.put(eip)
        return
    except Exception as e:
        os.dup2(old_stdout, sys.stdout.fileno())
        os.dup2(old_stderr, sys.stderr.fileno())
        os.dup2(old_stdin, sys.stdin.fileno())
        ei = sys.exc_info();
        info("run_path exception:", exc_info=ei)
        eip = (ei[0], str(ei[1]), traceback.extract_tb(ei[2]))
        q.put(eip)
        return
    finally:
        os.dup2(old_stdout, sys.stdout.fileno())
        os.dup2(old_stderr, sys.stderr.fileno())
        os.dup2(old_stdin, sys.stdin.fileno())
    q.put((None, "None", [(path, None, None, None)]))
    
class validationFile(object):
    
    def __init__(self, path, language, tempDir):
        self.path = path
        self.lm = language
        self.f = open(path)
        self.original = self.f.read()
        self.lexed = self.lm(self.original)
        self.scrubbed = self.lexed.scrubbed()
        self.f.close()
        self.mutatedLexemes = None
        self.mutatedLocation = None
        self.tempDir = tempDir
        self.mode = 'script'
        r = self.run(path)
        rscript = r
        if (r[0] != None):
            self.mode = 'module'
            r = self.run(path)
            if (r[0] != None):
                self.mode = 'module_indir'
                r = self.run(path)
        #info("Ran %s as a %s, got %s" % (self.path, self.mode, r[1]))
        if (r[0] != None):
          raise Exception("Couldn't run file: %s because %s" % (self.path, r[1]))
    
    def run(self, path):
        q = Queue()
        p = Process(target=runFile, args=(q,path,self.mode))
        p.start()
        try:
          r = q.get(True, 10)
        except Empty as e:
          r = (HaltingError, "Didn't halt.", [(path, None, None, None)])
        p.terminate()
        p.join()
        assert not p.is_alive()
        #assert r[2][-1][2] != "_get_code_from_file" # This seems to be legit
        return r

    
    def mutate(self, lexemes, location):
        assert isinstance(lexemes, ucSource)
        self.mutatedLexemes = self.lm(lexemes.deLex())
        self.mutatedLocation = location
        
    def runMutant(self):
        (mutantFileHandle, mutantFilePath) = mkstemp(suffix=".py", prefix="mutant", dir=self.tempDir)
        mutantFile = os.fdopen(mutantFileHandle, "w")
        mutantFile.write(self.mutatedLexemes.deLex())
        mutantFile.close()
        r = self.run(mutantFilePath)
        os.remove(mutantFilePath)
        return r
        
class modelValidation(object):
    
    def addValidationFile(self, files):
          """Add a file for validation..."""
          files = [files] if isinstance(files, str) else files
          assert isinstance(files, list)
          nSkipped = 0
          nAdded = 0
          for fi in files:
            try:
                vfi = validationFile(fi, self.lm, self.resultsDir)
                if len(vfi.lexed) > self.sm.windowSize:
                    self.validFiles.append(vfi)
                    info("Using %s in %s mode." % (fi, vfi.mode))
                    nAdded += 1
            except:
                info("Skipping %s !!!" % (fi), exc_info=sys.exc_info())
                nSkipped += 1
          info("Using: %i, Skipped: %i" % (nAdded, nSkipped)) 
    
    def genCorpus(self):
          """Create the corpus from the known-good file list."""
          for fi in self.validFiles:
            self.sm.trainLexemes(fi.scrubbed)
    
    def validate(self, mutation, n):
        """Run main validation loop."""
        trr = 0 # total reciprocal rank
        tr = 0 # total rank
        ttn = 0 # total in top n
        assert n > 0
        for fi in self.validFiles:
          assert isinstance(fi, validationFile)
          if fi.path in self.progress:
            progress = self.progress[fi.path]
          else:
            progress = 0
          info("Testing " + str(progress) + "/" + str(n) + " " + fi.path)
          for i in range(progress, n):
            merror = mutation(self, fi)
            if merror is not None:
              info(merror)
              break
            runException = fi.runMutant()
            if (runException[0] == None):
              exceptionName = "None"
            else:
              exceptionName = runException[0].__name__
            filename, line, func, text = runException[2][-1]
            if (fi.mutatedLocation.start.line == line):
              online = True
            else:
              online = False
            worst = self.sm.worstWindows(fi.mutatedLexemes)
            for j in range(0, len(worst)):
                #debug(str(worst[i][0][0].start) + " " + str(fi.mutatedLocation.start) + " " + str(worst[i][1]))
                if worst[j][0][0].start <= fi.mutatedLocation.start and worst[j][0][-1].end >= fi.mutatedLocation.end:
                    #debug(">>>> Rank %i (%s)" % (i, fi.path))
                    break
            info(" ".join(map(str, [mutation.__name__, j, fi.mutatedLocation.start.line, exceptionName, line])))
            if j >= len(worst):
              error(repr(worst))
              error(repr(fi.mutatedLocation))
              assert False
            self.csv.writerow([
              fi.path, 
              mutation.__name__, 
              j, 
              worst[j][1], 
              fi.mutatedLocation.type,
              fi.mutatedLocation.start.line,
              nonWord.sub('', fi.mutatedLocation.value), 
              exceptionName, 
              online,
              filename,
              line,
              func,
              worst[j][0][0].start.line])
            self.csvFile.flush()
            trr += 1/float(i+1)
            tr += float(i)
            if i < 5:
                ttn += 1
        mrr = trr/float(len(self.validFiles) * n)
        mr = tr/float(len(self.validFiles) * n)
        mtn = ttn/float(len(self.validFiles) * n)
        info("MRR %f MR %f M5+ %f" % (mrr, mr, mtn))
            
    def deleteRandom(self, vFile):
        """Delete a random token from a file."""
        ls = copy(vFile.scrubbed)
        token = ls.pop(randint(0, len(ls)-1))
        if token.type == 'ENDMARKER':
          return self.deleteRandom(vFile)
        vFile.mutate(ls, token)
        return None
            
    def insertRandom(self, vFile):
        ls = copy(vFile.scrubbed)
        token = ls[randint(0, len(ls)-1)]
        pos = randint(0, len(ls)-1)
        inserted = ls.insert(pos, token)
        if inserted[0].type == 'ENDMARKER':
          return self.insertRandom(vFile)
        vFile.mutate(ls, inserted[0])
        return None
            
    def replaceRandom(self, vFile):
        ls = copy(vFile.scrubbed)
        token = ls[randint(0, len(ls)-1)]
        pos = randint(0, len(ls)-2)
        oldToken = ls.pop(pos)
        if oldToken.type == 'ENDMARKER':
          return self.replaceRandom(vFile)
        inserted = ls.insert(pos, token)
        if inserted[0].type == 'ENDMARKER':
          return self.replaceRandom(vFile)
        vFile.mutate(ls, inserted[0])
        return None
        
    def dedentRandom(self, vFile):
        s = copy(vFile.original)
        lines = s.splitlines(True);
        while True:
          line = randint(0, len(lines)-1)
          if beginsWithWhitespace.match(lines[line]):
            lines[line][0] = ''
            break
        vFile.mutatedLexemes = vFile.lm("".join(lines))
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.INDENT, ' ', (line+1, 0), (line+1, 0)))
        return None
        
    def indentRandom(self, vFile):
        s = copy(vFile.original)
        lines = s.splitlines(True);
        line = randint(0, len(lines)-1)
        if beginsWithWhitespace.match(lines[line]):
          lines[line] = lines[line][0] + lines[line]
        else:
          lines[line] = " " + lines[line]
        vFile.mutatedLexemes = vFile.lm("".join(lines))
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.INDENT, ' ', (line+1, 0), (line+1, 0)))
        return None
    
    def punctRandom(self, vFile):
        s = copy(vFile.original)
        charPos = randint(1, len(s)-1)
        linesbefore = s[:charPos].splitlines(True)
        line = len(linesbefore)
        lineChar = len(linesbefore[-1])
        c = s[charPos:charPos+1]
        if (funny.match(c)):
          new = s[:charPos] + s[charPos+1:]
          vFile.mutatedLexemes = vFile.lm(new)
          vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
          return None
        else:
          return self.punctRandom(vFile)
    
    #def keyRandom(self, vFile):
        #s = copy(vFile.original)
        
    def nameRandom(self, vFile):
      return self.deleteWordRandom(vFile)

    def insertWordRandom(self, vFile):
        s = copy(vFile.original)
        while True:
          char = s[randint(1, len(s)-1)]
          charPos = randint(1, len(s)-1)
          linesbefore = s[:charPos].splitlines(True)
          line = len(linesbefore)
          lineChar = len(linesbefore[-1])
          c = s[charPos:charPos+1]
          if (name.match(char)):
            break
        new = s[:charPos] + char + s[charPos:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None

    def deleteWordRandom(self, vFile):
        s = copy(vFile.original)
        while True:
          charPos = randint(1, len(s)-1)
          linesbefore = s[:charPos].splitlines(True)
          line = len(linesbefore)
          lineChar = len(linesbefore[-1])
          c = s[charPos:charPos+1]
          if (name.match(c)):
            break
        new = s[:charPos] + s[charPos+1:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None
        
    def insertPunctRandom(self, vFile):
        s = copy(vFile.original)
        if not punct.search(s):
          return "No punctuation"
        while (True):
          char = s[randint(1, len(s)-1)]
          if (punct.match(char)):
            break
        charPos = randint(1, len(s)-1)
        linesbefore = s[:charPos].splitlines(True)
        line = len(linesbefore)
        lineChar = len(linesbefore[-1])
        c = s[charPos:charPos+1]
        new = s[:charPos] + char + s[charPos:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None

    def deleteNumRandom(self, vFile):
        s = copy(vFile.original)
        if not numeric.search(s):
          return "No numbers"
        positions = [x.start() for x in numeric.finditer(s)]
        while True:
          if (len(positions) == 1):
            charPos = positions[0]
          else:
            charPos = positions[randint(1, len(positions)-1)]
          linesbefore = s[:charPos].splitlines(True)
          line = len(linesbefore)
          lineChar = len(linesbefore[-1])
          c = s[charPos:charPos+1]
          if (numeric.match(c)):
            break
        new = s[:charPos] + s[charPos+1:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None

    def insertNumRandom(self, vFile):
        s = copy(vFile.original)
        char = str(randint(0, 9))
        charPos = randint(1, len(s)-1)
        linesbefore = s[:charPos].splitlines(True)
        line = len(linesbefore)
        lineChar = len(linesbefore[-1])
        c = s[charPos:charPos+1]
        new = s[:charPos] + char + s[charPos:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None

    def deletePunctRandom(self, vFile):
        s = copy(vFile.original)
        if not punct.search(s):
          return "No punctuation"
        while True:
          charPos = randint(1, len(s)-1)
          linesbefore = s[:charPos].splitlines(True)
          line = len(linesbefore)
          lineChar = len(linesbefore[-1])
          c = s[charPos:charPos+1]
          if (punct.match(c)):
            break
        new = s[:charPos] + s[charPos+1:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None

    def colonRandom(self, vFile):
        s = copy(vFile.original)
        while True:
          charPos = randint(1, len(s)-1)
          linesbefore = s[:charPos].splitlines(True)
          line = len(linesbefore)
          lineChar = len(linesbefore[-1])
          c = s[charPos:charPos+1]
          if (c == ':'):
            break
        new = s[:charPos] + s[charPos+1:]
        vFile.mutatedLexemes = vFile.lm(new)
        vFile.mutatedLocation = pythonLexeme.fromTuple((token.OP, c, (line, lineChar), (line, lineChar)))
        return None
      
    def __init__(self, source=None, language=pythonSource, resultsDir=None, corpus=mitlmCorpus):
        self.resultsDir = ((resultsDir or os.getenv("ucResultsDir", None)) or mkdtemp(prefix='ucValidation-'))
        if isinstance(source, str):
            raise NotImplementedError
        elif isinstance(source, list):
            self.validFileNames = source
        else:
            raise TypeError("Constructor arguments!")

        assert os.access(self.resultsDir, os.X_OK & os.R_OK & os.W_OK)
        self.csvPath = path.join(self.resultsDir, 'results.csv')
        self.progress = dict()
        try:
          self.csvFile = open(self.csvPath, 'r')
          self.csv = csv.reader(self.csvFile)
          for row in self.csv:
            if row[0] in self.progress:
              self.progress[row[0]] += 1 
            else:
              self.progress[row[0]] = 1
          self.csvFile.close()
        except (IOError):
          pass
        self.csvFile = open(self.csvPath, 'a')
        self.csv = csv.writer(self.csvFile)
        self.corpusPath = os.path.join(self.resultsDir, 'validationCorpus')
        self.cm = corpus(readCorpus=self.corpusPath, writeCorpus=self.corpusPath, order=10)
        self.lm = language
        self.sm = sourceModel(cm=self.cm, language=self.lm)
        self.validFiles = list()
        self.addValidationFile(self.validFileNames)
        self.genCorpus()

    def release(self):
        """Close files and stop MITLM"""
        self.cm.release()
        self.cm = None
        
    def __del__(self):
        """I am a destructor, but release should be called explictly."""
        assert not self.cm, "Destructor called before release()"

DELETE = modelValidation.deleteRandom
INSERT = modelValidation.insertRandom
REPLACE = modelValidation.replaceRandom
PUNCTUATION = modelValidation.punctRandom
NAMELIKE = modelValidation.nameRandom
COLON = modelValidation.colonRandom
DELETEWORDCHAR = modelValidation.deleteWordRandom
INSERTWORDCHAR = modelValidation.insertWordRandom
DELETENUMCHAR = modelValidation.deleteNumRandom
INSERTNUMCHAR = modelValidation.insertNumRandom
DELETEPUNCTCHAR = modelValidation.deletePunctRandom
INSERTPUNCTCHAR = modelValidation.insertPunctRandom
DELETESPACE = modelValidation.dedentRandom
INSERTSPACE = modelValidation.indentRandom

def main():
        testFileList = os.getenv("TEST_FILE_LIST", sys.argv[1])
        n = int(sys.argv[2])
        outDir = sys.argv[3]
        logging.getLogger().setLevel(logging.DEBUG)
        testProjectFiles = open(testFileList).read().splitlines()
        v = modelValidation(source=testProjectFiles, language=pythonSource, corpus=mitlmCorpus, resultsDir=outDir)
        if re.match('i', sys.argv[4]):
          v.validate(mutation=INSERT, n=n)
        if re.match('r', sys.argv[4]):
          v.validate(mutation=REPLACE, n=n)
        if re.match('d', sys.argv[4]):
          v.validate(mutation=DELETE, n=n)
        if re.match('s', sys.argv[4]):
          v.validate(mutation=DELETESPACE, n=n)
        if re.match('S', sys.argv[4]):
          v.validate(mutation=INSERTSPACE, n=n)
        #if re.match('p', sys.argv[4]):
          #v.validate(mutation=PUNCTUATION, n=n)
        if re.match('n', sys.argv[4]):
          v.validate(mutation=NAMELIKE, n=n)
        if re.match('c', sys.argv[4]):
          v.validate(mutation=COLON, n=n)
        if re.match('w', sys.argv[4]):
          v.validate(mutation=DELETEWORDCHAR, n=n)
        if re.match('W', sys.argv[4]):
          v.validate(mutation=INSERTWORDCHAR, n=n)
        if re.match('p', sys.argv[4]):
          v.validate(mutation=DELETEPUNCTCHAR, n=n)
        if re.match('P', sys.argv[4]):
          v.validate(mutation=INSERTPUNCTCHAR, n=n)
        if re.match('o', sys.argv[4]):
          v.validate(mutation=DELETENUMCHAR, n=n)
        if re.match('O', sys.argv[4]):
          v.validate(mutation=INSERTNUMCHAR, n=n)
        # TODO: assert csvs
        v.release()

if __name__ == '__main__':
    main()
