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
from unnaturalcode.mitlmCorpus import *
from unnaturalcode.pythonSource import *
from operator import itemgetter

from logging import debug, info, warning, error


class sourceModel(object):

    def __init__(self, cm=mitlmCorpus(), language=pythonSource, windowSize=20):
        self.cm = cm
        self.lang = language
        self.windowSize = windowSize

    def trainFile(self, files):
        """Blindly train on a set of files whether or not it compiles..."""
        files = [files] if isinstance(files, str) else files
        assert isinstance(files, list)
        for fi in files:
            sourceCode = slurp(fi)
            self.trainString(sourceCode)

    def stringifyAll(self, lexemes):
        """Clean up a list of lexemes and convert it to a list of strings"""
        return [language.stringify(i.ltype, i.val) for i in lexemes]

    def corpify(self, lexemes):
        """Corpify a string"""
        return self.cm.corpify(self.stringifyAll(lexemes))

    def sourceToScrubbed(self, sourceCode):
        return self.lang(sourceCode).scrubbed()

    def trainLexemes(self, lexemes):
        """Train on a lexeme sequence."""
        return self.cm.addToCorpus(self.stringifyAll(lexemes))

    def trainString(self, sourceCode):
        """Train on a source code string"""
        return self.trainLexemes(self.sourceToScrubbed(sourceCode))

    def queryString(self, sourceCode):
        return self.queryLexed(self.lang(sourceCode))

    def queryLexed(self, lexemes):
        return self.cm.queryCorpus(self.stringifyAll(lexemes))

    def predictLexed(self, lexemes):
        return self.cm.predictCorpus(self.stringifyAll(lexemes))

    def windowedQuery(self, lexemes, returnWindows=True):
        lastWindowStarts = len(lexemes)-self.windowSize
        if lastWindowStarts < 1:
          return [(lexemes, self.queryLexed(lexemes))]
        r = []
        for i in range(0,lastWindowStarts+1): # remember range is [)
            end = i+self.windowSize
            w = lexemes[i:end] # remember range is [)
            e = self.queryLexed(w)
            if returnWindows:
                r.append( (w,e) )
            else:
                r.append( (False,e) )
        return r

    def worstWindows(self, lexemes):
        lexemes = lexemes.scrubbed()
        unsorted = self.windowedQuery(lexemes)
        return sorted(unsorted, key=itemgetter(1), reverse=True)

    def release(self):
        self.cm.release()
