#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/file.h>
#include <fcntl.h>
#include <time.h>
#include <sys/stat.h>
#include <IOKit/hid/IOHIDManager.h>
#include <IOKit/hid/IOHIDKeys.h>
#include <CoreFoundation/CoreFoundation.h>

static int geti(IOHIDDeviceRef d, CFStringRef k){ int v=-1; CFNumberRef n=IOHIDDeviceGetProperty(d,k); if(n) CFNumberGetValue(n,kCFNumberIntType,&v); return v; }

static IOHIDDeviceRef find_dev(void) {
    IOHIDManagerRef mgr = IOHIDManagerCreate(kCFAllocatorDefault, kIOHIDOptionsTypeNone);
    CFMutableDictionaryRef m = CFDictionaryCreateMutable(kCFAllocatorDefault,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int vid=0x258a,pid=0x010c;
    CFNumberRef v=CFNumberCreate(kCFAllocatorDefault,kCFNumberIntType,&vid), p=CFNumberCreate(kCFAllocatorDefault,kCFNumberIntType,&pid);
    CFDictionarySetValue(m,CFSTR(kIOHIDVendorIDKey),v); CFDictionarySetValue(m,CFSTR(kIOHIDProductIDKey),p);
    IOHIDManagerSetDeviceMatching(mgr,m);
    CFSetRef ds=IOHIDManagerCopyDevices(mgr); CFIndex n=ds?CFSetGetCount(ds):0;
    IOHIDDeviceRef *a=calloc(n,sizeof(IOHIDDeviceRef)); if(ds) CFSetGetValues(ds,(const void**)a);
    IOHIDDeviceRef found=NULL;
    for(CFIndex i=0;i<n;i++){
        int up=geti(a[i],CFSTR(kIOHIDPrimaryUsagePageKey)), u=geti(a[i],CFSTR(kIOHIDPrimaryUsageKey));
        if(up==1 && u==0x80){ found=(IOHIDDeviceRef)CFRetain(a[i]); break; }
    }
    return found;
}

static int save_resp(const char *dir, const char *name, unsigned char cmd, unsigned char sub, unsigned short size, unsigned char total, unsigned char idx) {
    IOHIDDeviceRef d = find_dev();
    if(!d){ fprintf(stderr,"device not found\n"); return 1; }
    IOReturn r = IOHIDDeviceOpen(d, kIOHIDOptionsTypeNone);
    if(r != kIOReturnSuccess){ fprintf(stderr,"open failed 0x%x\n",r); return 1; }
    unsigned char req[520]; memset(req,0,sizeof req);
    req[0]=0x06; req[1]=cmd; req[2]=sub; req[3]=0x00; req[4]=total; req[5]=idx;
    req[6]=size & 0xff; req[7]=size >> 8;
    IOReturn sr = IOHIDDeviceSetReport(d, kIOHIDReportTypeFeature, 6, req, sizeof req);
    usleep(30000);
    unsigned char buf[520]; memset(buf,0,sizeof buf); buf[0]=6; CFIndex len=sizeof buf;
    IOReturn rr = IOHIDDeviceGetReport(d, kIOHIDReportTypeFeature, 6, buf, &len);
    printf("%-10s cmd=%02x sub=%02x size=%u total=%u idx=%u set=0x%x get=0x%x len=%ld\n", name, cmd, sub, size, total, idx, sr, rr, (long)len);
    int ok = (sr==kIOReturnSuccess && rr==kIOReturnSuccess && len>0);
    if(ok) {
        char path[512]; snprintf(path,sizeof path,"%s/%s.bin",dir,name);
        FILE *f=fopen(path,"wb"); if(!f){perror(path); ok=0;} else { fwrite(buf,1,len,f); fclose(f); printf("  saved %s (%ld bytes)\n",path,(long)len); }
    }
    IOHIDDeviceClose(d,kIOHIDOptionsTypeNone); CFRelease(d);
    return ok?0:1;
}

int main(int argc, char **argv){
    int lockfd = open("/tmp/x87-hid.lock", O_CREAT|O_RDWR, 0666);
    if(lockfd >= 0) flock(lockfd, LOCK_EX);
    const char *dir = argc>1 ? argv[1] : "backup";
    mkdir(dir,0755);
    // identity
    {
        IOHIDDeviceRef d=find_dev(); if(!d){fprintf(stderr,"device not found\n");return 1;}
        if(IOHIDDeviceOpen(d,kIOHIDOptionsTypeNone)!=kIOReturnSuccess){fprintf(stderr,"open failed\n");return 1;}
        unsigned char req[520]; memset(req,0,sizeof req);
        req[0]=6; req[1]=0x82; req[2]=1; req[3]=0; req[4]=1; req[5]=0; req[6]=6;
        IOReturn sr=IOHIDDeviceSetReport(d,kIOHIDReportTypeFeature,6,req,sizeof req); usleep(50000);
        unsigned char buf[520]; memset(buf,0,sizeof buf); buf[0]=6; CFIndex len=sizeof buf;
        IOReturn rr=IOHIDDeviceGetReport(d,kIOHIDReportTypeFeature,6,buf,&len);
        printf("identity   set=0x%x get=0x%x len=%ld\n",sr,rr,(long)len);
        if(rr==kIOReturnSuccess&&len>0){char path[512];snprintf(path,sizeof path,"%s/identity.bin",dir);FILE*f=fopen(path,"wb");fwrite(buf,1,len,f);fclose(f);printf("  saved %s\n",path);}
        IOHIDDeviceClose(d,kIOHIDOptionsTypeNone); CFRelease(d);
    }
    int fail=0;
    fail |= save_resp(dir,"config",0x84,0x00,128,1,0);
    fail |= save_resp(dir,"colors",0x8A,0x00,512,1,0);
    fail |= save_resp(dir,"perkey",0x86,0x00,512,1,0);
    fail |= save_resp(dir,"keys-base",0x83,0x00,512,1,0);
    fail |= save_resp(dir,"keys-fn",0x83,0x01,512,1,0);
    for(int i=0;i<8;i++){
        char name[32]; snprintf(name,sizeof name,"macro-%d",i);
        fail |= save_resp(dir,name,0x85,0x00,512,8,(unsigned char)i);
    }
    return fail?1:0;
}
