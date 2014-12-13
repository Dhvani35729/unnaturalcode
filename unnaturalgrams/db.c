/* db.c -- Database Interface for UnnaturalGrams
 * 
 * Copyright 2014 Joshua Charles Campbell
 *
 * This file is part of UnnaturalCode.
 *
 * UnnaturalCode is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 * 
 * UnnaturalCode is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with UnnaturalCode.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "db.h"
#include "copper.h"

#include <sys/stat.h>
#include <unistd.h>
#include <string.h>

void ug_commit(struct ug_Corpus * corpus) {
  Ad(( corpus->inTxn  ));
  if (corpus->readOnly) {
    mdb_txn_reset(corpus->mdbTxn);
  } else {  
    Ad(( mdb_txn_commit(corpus->mdbTxn) == 0 ));
    corpus->mdbTxn = NULL;
  }
  corpus->inTxn = 0;
}

void ug_abort(struct ug_Corpus * corpus) {
  mdb_txn_abort(corpus->mdbTxn);
  corpus->mdbTxn = NULL;
  corpus->inTxn = 0;
}

void ug_beginRW(struct ug_Corpus * corpus) {
  Ad(( ! corpus->inTxn  ));
  if (corpus->readOnly) {
    corpus->readOnly = 0;
    ug_abort(corpus);
  }
  Ad(( corpus->mdbTxn == NULL ));
  Ad(( mdb_txn_begin(corpus->mdbEnv, NULL, 0, &(corpus->mdbTxn)) == 0 ));
  corpus->inTxn = 1;
}

void ug_beginRO(struct ug_Corpus * corpus) {
  if (corpus->readOnly) {
    Ad(( corpus->mdbTxn != NULL ));
    mdb_txn_reset(corpus->mdbTxn);
  } else {
    Ad(( corpus->mdbTxn == NULL ));
    Ad(( mdb_txn_begin(corpus->mdbEnv, NULL, MDB_RDONLY, &(corpus->mdbTxn)) == 0 ));    
    corpus->readOnly = 1;
  }
  corpus->inTxn = 1;
}


int ug_openDB(char * path, struct ug_Corpus * corpus) {
  struct stat s;
  MDB_txn * mdbTxn = NULL;
  
  ASYS(( stat(path, &s) == 0 ));
  ASYS(( access(path, R_OK | W_OK | X_OK) == 0 ));

  Ad(( mdb_env_create(&(corpus->mdbEnv)) == 0 ));
  Ad(( S_ISDIR(s.st_mode) ));
  Ad(( mdb_env_open(corpus->mdbEnv, path, 0, 0666) == 0 ));
  Ad(( mdb_txn_begin(corpus->mdbEnv, NULL, 0, &mdbTxn) == 0 ));
  Ad(( mdb_dbi_open(mdbTxn, NULL, 0, &(corpus->mdbDbi)) == 0 ));
  Ad(( mdb_txn_commit(mdbTxn) == 0 )); mdbTxn = NULL;
  
  return 0;
}

int ug_closeDB(struct ug_Corpus * corpus) {
      mdb_env_close(corpus->mdbEnv); 
      corpus->mdbEnv = NULL;
      return 0;
}

int ug_existsByC(struct  ug_Corpus * corpus, char * cKey) {
  struct MDB_val key;
  struct MDB_val data;
  int r;

  key.mv_data = cKey;
  key.mv_size = strlen(key.mv_data)+1;  
  
  r = mdb_get(corpus->mdbTxn, corpus->mdbDbi, &key, &data);
  
  if (r == 0) {
    return 1;
  } else if (r == MDB_NOTFOUND) {
    return 0;
  }
  E(("LMDB Error %i: %s", r, mdb_strerror(r)));
  return 0;
}

size_t ug_readOrNull(struct  ug_Corpus * corpus, size_t keyLength, void * keyData,
              void ** valueData) {
  struct MDB_val key;
  struct MDB_val data;
  int r;

  key.mv_data = keyData;
  key.mv_size = keyLength;
  
  Ad((key.mv_size > 0));
  
  r = mdb_get(corpus->mdbTxn, corpus->mdbDbi, &key, &data);
  
  if (r == 0) {
    *valueData = data.mv_data;
    return data.mv_size;
  } else if (r == MDB_NOTFOUND) {
    *valueData = NULL;
    return 0;
  }
  E(("LMDB Error %i: %s", r, mdb_strerror(r)));
  return 0;
}

size_t ug_read(struct  ug_Corpus * corpus, size_t keyLength, void * keyData,
              void ** valueData) {
  struct MDB_val key;
  struct MDB_val data;
  int r;

  key.mv_data = keyData;
  key.mv_size = keyLength;
  
  Ad((key.mv_size > 0));
  
  r = mdb_get(corpus->mdbTxn, corpus->mdbDbi, &key, &data);
  
  if (r == 0) {
    *valueData = data.mv_data;
    return data.mv_size;
  }
  E(("LMDB Error %i: %s", r, mdb_strerror(r)));
  return 0;
}

void * ug_readNOrNull(struct  ug_Corpus * corpus, size_t keyLength, void * keyData,
              size_t valueSize) {
  void * r = NULL;
  Ad(( ug_readOrNull(corpus, keyLength, keyData, &r) == valueSize ));
  return r;
}

void * ug_readN(struct  ug_Corpus * corpus, size_t keyLength, void * keyData,
              size_t valueSize) {
  void * r = NULL;
  Ad(( ug_read(corpus, keyLength, keyData, &r) == valueSize ));
  return r;
}

uint64_t ug_readUInt64(struct  ug_Corpus * corpus,
                       size_t keyLength, void * keyData) {
  void * r = NULL;
  
  r = ug_readN(corpus, keyLength, keyData, sizeof(uint64_t));
  return *((uint64_t *) r);
}

uint64_t ug_readUInt64OrZero(struct  ug_Corpus * corpus,
                       size_t keyLength, void * keyData) {
  void * r = NULL;
  
  r = ug_readNOrNull(corpus, keyLength, keyData, sizeof(uint64_t));
  if (r == NULL) {
    return 0;
  } else {
    return *((uint64_t *) r);
  }
}

uint64_t ug_readUInt64ByC(struct  ug_Corpus * corpus, char * cKey) {
  return ug_readUInt64(corpus, strlen(cKey)+1, cKey);
}

void ug_write(struct  ug_Corpus * corpus, size_t keyLength, void * keyData,
              size_t valueLength, void * valueData)
{
  struct MDB_val key;
  struct MDB_val data;
  int r;

  key.mv_data = keyData;
  key.mv_size = keyLength;  
  
  data.mv_data = valueData;
  data.mv_size = valueLength;
  
  r = mdb_put(corpus->mdbTxn, corpus->mdbDbi, &key, &data, MDB_NOOVERWRITE);
  
  if (r != 0) {
    E(("LMDB Error %i: %s", r, mdb_strerror(r)));
  }
}

void ug_writeUInt64ByC(struct  ug_Corpus * corpus, char * cKey, uint64_t value) {
  ug_write(corpus, strlen(cKey)+1, cKey, sizeof(value), &value);
}

int ug_createDB(char * path, struct ug_Corpus * corpus) {
  MDB_txn * mdbTxn = NULL;
  MDB_env * mdbEnv = NULL;
  MDB_dbi mdbDbi = 0;
  
  ASYS(( mkdir(path, 0777) == 0 ));
  
  Ad(( mdb_env_create(&mdbEnv) == 0 ));
  Ad(( mdb_env_open(mdbEnv, path, 0, 0666) == 0 ));
  Ad(( mdb_txn_begin(mdbEnv, NULL, 0, &mdbTxn) == 0 ));
  Ad(( mdb_dbi_open(mdbTxn, NULL, MDB_CREATE, &(mdbDbi)) == 0 ));
  Ad(( mdb_txn_commit(mdbTxn) == 0 )); mdbTxn = NULL;
  mdb_env_close(mdbEnv); mdbEnv = NULL;
  
  return ug_openDB(path, corpus);
}
