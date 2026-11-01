#define _GNU_SOURCE
#include <fcntl.h>
#include <stdarg.h>
#include <dlfcn.h>
#include <errno.h>
#include <time.h>
#include <stdint.h>
static int dispatch(const char *symbol,int fd,int cmd,va_list ap) {
 int (*real)(int,int,...)=dlsym(RTLD_NEXT,symbol);
 if(cmd==F_GETFD || cmd==F_GETFL || cmd==F_GETOWN || cmd==F_GETSIG || cmd==F_GETLEASE || cmd==F_GETPIPE_SZ) return real(fd,cmd);
 uintptr_t arg=va_arg(ap,uintptr_t);
 if(cmd==F_SETLKW || cmd==F_OFD_SETLKW) {
  int nonblocking=(cmd==F_SETLKW)?F_SETLK:F_OFD_SETLK;
  for(;;) {
   int rc=real(fd,nonblocking,arg);
   if(rc==0 || (errno!=EAGAIN && errno!=EACCES)) return rc;
   struct timespec delay={0,20000000};
   if(nanosleep(&delay,0)<0)return -1;
  }
 }
 return real(fd,cmd,arg);
}
int fcntl(int fd,int cmd,...) {va_list ap;va_start(ap,cmd);int r=dispatch("fcntl",fd,cmd,ap);va_end(ap);return r;}
int fcntl64(int fd,int cmd,...) {va_list ap;va_start(ap,cmd);int r=dispatch("fcntl64",fd,cmd,ap);va_end(ap);return r;}
