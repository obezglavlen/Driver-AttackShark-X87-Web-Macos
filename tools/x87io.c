#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/file.h>
#include <fcntl.h>
#include <IOKit/hid/IOHIDManager.h>
#include <IOKit/hid/IOHIDKeys.h>
#include <CoreFoundation/CoreFoundation.h>

static int geti(IOHIDDeviceRef d, CFStringRef k){ int v=-1; CFNumberRef n=IOHIDDeviceGetProperty(d,k); if(n) CFNumberGetValue(n,kCFNumberIntType,&v); return v; }

static IOHIDDeviceRef find_dev(void){
    IOHIDManagerRef mgr=IOHIDManagerCreate(kCFAllocatorDefault,kIOHIDOptionsTypeNone);
    CFMutableDictionaryRef m=CFDictionaryCreateMutable(kCFAllocatorDefault,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int vid=0x258a,pid=0x010c;
    CFNumberRef v=CFNumberCreate(kCFAllocatorDefault,kCFNumberIntType,&vid),p=CFNumberCreate(kCFAllocatorDefault,kCFNumberIntType,&pid);
    CFDictionarySetValue(m,CFSTR(kIOHIDVendorIDKey),v); CFDictionarySetValue(m,CFSTR(kIOHIDProductIDKey),p);
    IOHIDManagerSetDeviceMatching(mgr,m);
    CFSetRef ds=IOHIDManagerCopyDevices(mgr); CFIndex n=ds?CFSetGetCount(ds):0;
    IOHIDDeviceRef *a=calloc(n,sizeof(IOHIDDeviceRef)); if(ds) CFSetGetValues(ds,(const void**)a);
    IOHIDDeviceRef found=NULL;
    for(CFIndex i=0;i<n;i++){ if(geti(a[i],CFSTR(kIOHIDPrimaryUsagePageKey))==1 && geti(a[i],CFSTR(kIOHIDPrimaryUsageKey))==0x80){ found=(IOHIDDeviceRef)CFRetain(a[i]); break; } }
    return found;
}

static int hexval(char c){ if(c>='0'&&c<='9')return c-'0'; if(c>='a'&&c<='f')return c-'a'+10; if(c>='A'&&c<='F')return c-'A'+10; return -1; }

int main(int argc,char**argv){
    int lockfd = open("/tmp/x87-hid.lock", O_CREAT|O_RDWR, 0666);
    if(lockfd >= 0) flock(lockfd, LOCK_EX);
    if(argc<5){ fprintf(stderr,"usage:\n  %s read  <outfile> <cmd_hex> <sub_hex> <size> [total] [idx]\n  %s write <infile>  <cmd_hex> <sub_hex> <size> [total] [idx]\n",argv[0],argv[0]); return 2; }
    int is_write = strcmp(argv[1],"write")==0;
    const char *file=argv[2];
    unsigned char cmd=(unsigned char)strtoul(argv[3],NULL,16);
    unsigned char sub=(unsigned char)strtoul(argv[4],NULL,16);
    unsigned short size=(unsigned short)strtoul(argv[5],NULL,0);
    unsigned char total=argc>6?(unsigned char)strtoul(argv[6],NULL,0):1;
    unsigned char idx=argc>7?(unsigned char)strtoul(argv[7],NULL,0):0;
    if(size>512){fprintf(stderr,"size must be <=512\n");return 2;}
    IOHIDDeviceRef d=find_dev(); if(!d){fprintf(stderr,"keyboard not found (258a:010c)\n");return 1;}
    IOReturn opr=IOHIDDeviceOpen(d,kIOHIDOptionsTypeNone);
    if(opr!=kIOReturnSuccess){FILE*lf=fopen("/tmp/x87io-errors.log","a");if(lf){fprintf(lf,"open failed 0x%x uid=%d\n",opr,getuid());fclose(lf);}fprintf(stderr,"open failed 0x%x\n",opr);return 1;}
    unsigned char req[520]; memset(req,0,sizeof req);
    req[0]=0x06; req[1]=cmd; req[2]=sub; req[3]=0x00; req[4]=total; req[5]=idx; req[6]=size&0xff; req[7]=size>>8;
    if(is_write){
        FILE*f=fopen(file,"rb"); if(!f){perror(file);return 1;}
        size_t got=fread(req+8,1,size,f); fclose(f);
        if(got!=size){fprintf(stderr,"read %zu of %u bytes\n",got,size);return 1;}
        IOReturn sr=IOHIDDeviceSetReport(d,kIOHIDReportTypeFeature,6,req,sizeof req);
        printf("write cmd=%02x sub=%02x size=%u total=%u idx=%u -> 0x%x\n",cmd,sub,size,total,idx,sr);
        IOHIDDeviceClose(d,kIOHIDOptionsTypeNone); return sr==kIOReturnSuccess?0:1;
    } else {
        IOReturn sr=IOHIDDeviceSetReport(d,kIOHIDReportTypeFeature,6,req,sizeof req);
        usleep(30000);
        unsigned char buf[520]; memset(buf,0,sizeof buf); buf[0]=6; CFIndex len=sizeof buf;
        IOReturn rr=IOHIDDeviceGetReport(d,kIOHIDReportTypeFeature,6,buf,&len);
        printf("read cmd=%02x sub=%02x size=%u total=%u idx=%u -> set=0x%x get=0x%x len=%ld\n",cmd,sub,size,total,idx,sr,rr,(long)len);
        if(sr==kIOReturnSuccess&&rr==kIOReturnSuccess&&len>0){
            FILE*f=fopen(file,"wb"); if(!f){perror(file);return 1;} fwrite(buf,1,len,f); fclose(f); printf("saved %s (%ld bytes)\n",file,(long)len);
        }
        IOHIDDeviceClose(d,kIOHIDOptionsTypeNone); return (sr==kIOReturnSuccess&&rr==kIOReturnSuccess)?0:1;
    }
}
