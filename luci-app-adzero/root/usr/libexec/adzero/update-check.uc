'use strict';
// Parse official GitHub metadata as data, never as executable shell code.
// Only published, non-draft numeric SemVer tags with a GitHub SHA-256 digest
// for the exact "install.sh" release asset can become upgrade candidates.
import * as fs from 'fs';

try {
	let path=shift(ARGV);
	let mode=shift(ARGV)??'api';
	if(length(ARGV)||index(['api','bootstrap'],mode)<0)exit(2);
	// mktemp and Python tempfile may use '_' in their eight-character
	// random suffix. Keep the exact private directory, stem and length.
	if (!path || !match(path,/^\/tmp\/adzero-update\/releases\.[A-Za-z0-9_]{8}$/)) exit(2);
	let stat=fs.lstat(path);
	// rpcd normally runs as root; verify ownership against our actual UID so
	// isolated OpenWrt userspace tests retain this same trust boundary.
	if (stat?.type!='file' || stat.size>1048576 || stat.uid!=fs.stat('/proc/self')?.uid || (stat.mode&077)!=0) exit(2);
	let raw=fs.readfile(path);
	if(mode=='bootstrap'){
		// This is the same pinned, stable entrypoint used by manual installs.
		// Accept only its exact repository/asset and one unambiguous digest.
		if(stat.size>65536||substr(raw,0,10)!='#!/bin/sh\n')exit(2);
		let urls=[],digests=[];
		for(let line in split(raw,'\n')){
			if(index(line,'INSTALL_URL=')==0)push(urls,substr(line,12));
			if(index(line,'INSTALL_SHA256=')==0)push(digests,substr(line,15));
		}
		if(length(urls)!=1||length(digests)!=1||!match(digests[0],/^[a-f0-9]{64}$/))exit(2);
		let tag=match(urls[0],/^https:\/\/github[.]com\/slobys\/AdZero\/releases\/download\/(v[0-9]{1,3}[.][0-9]{1,3}[.][0-9]{1,3})\/install[.]sh$/);
		if(!tag)exit(2);
		printf('%s %s\n',tag[1],digests[0]);exit(0);
	}
	let releases=json(raw);
	if (type(releases)!='array') exit(2);
	let found=null, parts=null;
	for (let release in releases) {
		if (release?.draft || release?.prerelease || type(release?.tag_name)!='string' || !match(release.tag_name,/^v[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$/)) continue;
		let digits=split(substr(release.tag_name,1),'.');
		if (length(digits)!=3) continue;
		let values=[int(digits[0]),int(digits[1]),int(digits[2])];
		let asset=null;
		for (let candidate in release.assets??[]) {
			if (candidate?.name=='install.sh' && type(candidate.digest)=='string' &&
				match(candidate.digest,/^sha256:[a-f0-9]{64}$/)) {
				asset=candidate;
				break;
			}
		}
		if (!asset) continue;
		if (!found || values[0]>parts[0] ||
			values[0]==parts[0] && (values[1]>parts[1] ||
			values[1]==parts[1] && values[2]>parts[2])) {
			found={tag:release.tag_name,digest:substr(asset.digest,7)};
			parts=values;
		}
	}
	if (!found) exit(3);
	printf('%s %s\n',found.tag,found.digest);
} catch(e) { exit(2); }
