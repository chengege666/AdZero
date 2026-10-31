'use strict';
import * as fs from 'fs';
// flock belongs to the open file description. ctl and its active descendants
// retain descriptor 9 after this short helper exits. Never explicitly unlock it.
let handle=fs.fdopen(9,'a');
if(!handle || !handle.lock('xn'))exit(75);
exit(0);
