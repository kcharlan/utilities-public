#define _DARWIN_C_SOURCE
#include "runner.h"
#include "util/atomic.h"
#include "util/fileio.h"
#include <dirent.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <pwd.h>
#include <signal.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>
#include "testing/hooks.h"
#include <errno.h>
static int temporary_count(const char *dir);

TEST(runtime_cleanup_live_peer_temp_classifies_wall_and_rename) {
    const char *prior=getenv("COLOPHON_TEST_WALL_MS");char *saved=prior?strdup(prior):NULL;
    for(int future=0;future<2;future++){
        char root[]="/tmp/colophon-live-peer.XXXXXX";ASSERT_TRUE(mkdtemp(root));
        char temp[512],target[512];snprintf(temp,sizeof temp,"%s/.synthetic-peer.tmp",root);
        snprintf(target,sizeof target,"%s/published",root);
        int fd=open(temp,O_RDWR|O_CREAT|O_EXCL,0600);ASSERT_TRUE(fd>=0);
        ASSERT_EQ(9,write(fd,"Synthetic",9));struct stat held,observed;ASSERT_EQ(0,fstat(fd,&held));
        int64_t wall=(int64_t)held.st_mtimespec.tv_sec*1000+held.st_mtimespec.tv_nsec/1000000;
        char clock[64];snprintf(clock,sizeof clock,"%lld",(long long)(wall+(future?7200000:0)));
        setenv("COLOPHON_TEST_WALL_MS",clock,1);ASSERT_EQ(ERR_OK,ensure_runtime_home(root).code);
        if(future){ASSERT_EQ(-1,lstat(temp,&observed));ASSERT_EQ(ENOENT,errno);
            ASSERT_EQ(-1,rename(temp,target));ASSERT_EQ(ENOENT,errno);}
        else {ASSERT_EQ(0,lstat(temp,&observed));ASSERT_EQ(held.st_ino,observed.st_ino);
            ASSERT_EQ(0,rename(temp,target));ASSERT_EQ(0,unlink(target));}
        ASSERT_EQ(0,fstat(fd,&observed));ASSERT_EQ(held.st_ino,observed.st_ino);
        ASSERT_EQ(0,close(fd));ASSERT_EQ(0,rmdir(root));
    }
    if(saved){setenv("COLOPHON_TEST_WALL_MS",saved,1);free(saved);}else unsetenv("COLOPHON_TEST_WALL_MS");
}

TEST(cli_original_atomic_complete_replacement_and_home_boundaries) {
    char root[]="/tmp/colophon-original-atomic.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    char path[512];snprintf(path,sizeof path,"%s/synthetic.bin",root);
    ASSERT_EQ(ERR_OK,atomic_write(path,"Synthetic old content",21).code);
    struct stat before,after;ASSERT_EQ(0,stat(path,&before));
    char bytes[22000];for(size_t i=0;i<1000;i++)memcpy(bytes+22*i,"Synthetic new content\n",22);
    ASSERT_EQ(ERR_OK,atomic_write(path,bytes,sizeof bytes).code);ASSERT_EQ(0,stat(path,&after));
    ASSERT_TRUE(before.st_ino!=after.st_ino);ASSERT_EQ(0600,after.st_mode&0777);ASSERT_EQ(0,temporary_count(root));
    char *actual=NULL;size_t length;ASSERT_EQ(ERR_OK,file_read_all(path,&actual,&length).code);
    ASSERT_EQ(sizeof bytes,length);ASSERT_EQ(0,memcmp(bytes,actual,length));free(actual);unlink(path);rmdir(root);
    const char *prior=getenv("HOME");char *saved=prior?strdup(prior):NULL;
    setenv("HOME","/tmp/synthetic-user-home",1);char *display=NULL;
    ASSERT_EQ(ERR_OK,file_abbreviate_home("/tmp/synthetic-user-home",&display).code);ASSERT_STREQ("~",display);free(display);
    ASSERT_EQ(ERR_OK,file_abbreviate_home("/tmp/synthetic-user-home/.codex",&display).code);ASSERT_STREQ("~/.codex",display);free(display);
    ASSERT_EQ(ERR_OK,file_abbreviate_home("/tmp/synthetic-user-home-other/.codex",&display).code);
    ASSERT_STREQ("/tmp/synthetic-user-home-other/.codex",display);free(display);
    if(saved){setenv("HOME",saved,1);free(saved);}else unsetenv("HOME");
}

TEST(atomic_fchmod_and_fsync_failures_preserve_identity_and_close_fd) {
    const char *points[]={"atomic_fchmod","atomic_fsync","atomic_replace"};
    for(size_t i=0;i<3;i++){
        char root[]="/tmp/colophon-atomic-hook.XXXXXX";ASSERT_TRUE(mkdtemp(root));
        char path[512];snprintf(path,sizeof path,"%s/synthetic.bin",root);
        ASSERT_EQ(ERR_OK,atomic_write(path,"Synthetic old content",21).code);
        struct stat before,after;ASSERT_EQ(0,stat(path,&before));
        int expected=open(root,O_RDONLY);ASSERT_TRUE(expected>=0);close(expected);
        int guard=open(root,O_RDONLY);ASSERT_TRUE(guard>=0);
        setenv("COLOPHON_TEST_FAULT",points[i],1);
        Err result=atomic_write(path,"Synthetic new content",21);
        unsetenv("COLOPHON_TEST_FAULT");
        ASSERT_EQ(ERR_IO,result.code);ASSERT_EQ(0,stat(path,&after));
        ASSERT_EQ(1,cp_atomic_close_count());
        ASSERT_EQ(-1,fstat(cp_atomic_fd(),&after));ASSERT_EQ(EBADF,errno);
        ASSERT_EQ(0,stat(path,&after));
        ASSERT_EQ(before.st_ino,after.st_ino);ASSERT_EQ(0600,after.st_mode&0777);
        ASSERT_EQ(0,fstat(guard,&after));close(guard);
        int available=open(root,O_RDONLY);ASSERT_EQ(expected,available);close(available);
        char *bytes=NULL;size_t length=0;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&length).code);
        ASSERT_STREQ("Synthetic old content",bytes);free(bytes);ASSERT_EQ(0,temporary_count(root));
        unlink(path);rmdir(root);
    }
}

static int temporary_count(const char *dir) {
    DIR *d=opendir(dir); ASSERT_TRUE(d); int count=0; struct dirent *e;
    while ((e=readdir(d))) if (e->d_name[0]=='.' && strstr(e->d_name,".tmp")) count++;
    closedir(d); return count;
}
TEST(atomic_write_creates_private_parents_and_replaces) {
    char root[]="/tmp/colophon-atomic.XXXXXX"; ASSERT_TRUE(mkdtemp(root));
    char parent[512], path[512]; snprintf(parent,sizeof(parent),"%s/nested",root);
    snprintf(path,sizeof(path),"%s/nested/data.json",root);
    mode_t previous_umask=umask(0);
    Err result=atomic_write(path,"first",5);umask(previous_umask);ASSERT_EQ(ERR_OK,result.code);
    struct stat st; ASSERT_EQ(0,stat(parent,&st)); ASSERT_EQ(0700,st.st_mode & 0777);
    ASSERT_EQ(0,stat(path,&st)); ASSERT_EQ(0600,st.st_mode & 0777);
    ASSERT_EQ(ERR_OK,atomic_write(path,"replacement",11).code);
    char *bytes=NULL; size_t n=0; ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);
    ASSERT_EQ(11,n); ASSERT_STREQ("replacement",bytes); free(bytes);
    ASSERT_EQ(0,temporary_count(parent));
    unlink(path); rmdir(parent); rmdir(root);
}
TEST(atomic_rename_failure_removes_temporary) {
    char root[]="/tmp/colophon-atomic.XXXXXX"; ASSERT_TRUE(mkdtemp(root));
    char path[512]; snprintf(path,sizeof(path),"%s/directory",root); ASSERT_EQ(0,mkdir(path,0700));
    ASSERT_EQ(ERR_IO,atomic_write(path,"bytes",5).code);
    ASSERT_EQ(0,temporary_count(root));
    rmdir(path); rmdir(root);
}
TEST(file_read_all_grows_and_preserves_embedded_nul) {
    char root[]="/tmp/colophon-file.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    char path[512];snprintf(path,sizeof(path),"%s/bytes",root);
    char fixture[20000];for(size_t i=0;i<sizeof(fixture);i++)fixture[i]=(char)(i%127);
    ASSERT_EQ(ERR_OK,atomic_write(path,fixture,sizeof(fixture)).code);
    char *bytes=NULL;size_t length=0;
    ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&length).code);ASSERT_EQ(sizeof(fixture),length);
    ASSERT_EQ(0,memcmp(fixture,bytes,length));ASSERT_EQ(0,bytes[length]);free(bytes);
    char child[512];snprintf(child,sizeof(child),"%s/bytes/child",root);
    ASSERT_EQ(ERR_IO,atomic_write(child,"bad",3).code);ASSERT_EQ(0,temporary_count(root));
    ASSERT_EQ(ERR_IO,file_read_all(root,&bytes,&length).code);
    unlink(path);rmdir(root);
}
TEST(atomic_write_failure_preserves_old_bytes_and_closes_fd) {
    char root[]="/tmp/colophon-atomic.XXXXXX"; ASSERT_TRUE(mkdtemp(root));
    char path[512];snprintf(path,sizeof(path),"%s/data",root);
    ASSERT_EQ(ERR_OK,atomic_write(path,"old",3).code);
    struct rlimit previous,limited;ASSERT_EQ(0,getrlimit(RLIMIT_FSIZE,&previous));limited=previous;limited.rlim_cur=1;
    void (*previous_signal)(int)=signal(SIGXFSZ,SIG_IGN);
    ASSERT_EQ(0,setrlimit(RLIMIT_FSIZE,&limited));
    int baseline_fd=open(root,O_RDONLY);ASSERT_TRUE(baseline_fd>=0);close(baseline_fd);
    Err result=atomic_write(path,"new bytes",9);
    ASSERT_EQ(0,setrlimit(RLIMIT_FSIZE,&previous));signal(SIGXFSZ,previous_signal);
    ASSERT_EQ(ERR_IO,result.code);ASSERT_EQ(0,temporary_count(root));
    int after_fd=open(root,O_RDONLY);ASSERT_EQ(baseline_fd,after_fd);close(after_fd);
    char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);
    ASSERT_STREQ("old",bytes);free(bytes);unlink(path);rmdir(root);
}
TEST(runtime_home_expands_named_user_and_trims_home_slashes) {
    const char *home=getenv("HOME"),*setting=getenv("COLOPHON_HOME");
    char *saved_home=home?strdup(home):NULL,*saved_setting=setting?strdup(setting):NULL;
    char *path=NULL;
    setenv("HOME","/tmp/synthetic-home///",1);unsetenv("COLOPHON_HOME");
    ASSERT_EQ(ERR_OK,runtime_home(&path).code);ASSERT_STREQ("/tmp/synthetic-home/.colophon",path);free(path);
    struct passwd *pw=getpwuid(getuid());ASSERT_TRUE(pw);
    char named[512];snprintf(named,sizeof(named),"~%s/custom",pw->pw_name);
    char expected[512];snprintf(expected,sizeof(expected),"%s/custom",pw->pw_dir);
    setenv("COLOPHON_HOME",named,1);ASSERT_EQ(ERR_OK,runtime_home(&path).code);ASSERT_STREQ(expected,path);free(path);
    unsetenv("HOME");unsetenv("COLOPHON_HOME");
    snprintf(expected,sizeof(expected),"%s/.colophon",pw->pw_dir);
    ASSERT_EQ(ERR_OK,runtime_home(&path).code);ASSERT_STREQ(expected,path);free(path);
    setenv("COLOPHON_HOME","",1);ASSERT_EQ(ERR_OK,runtime_home(&path).code);ASSERT_STREQ(".",path);free(path);
    if(saved_home){setenv("HOME",saved_home,1);free(saved_home);}else unsetenv("HOME");
    if(saved_setting){setenv("COLOPHON_HOME",saved_setting,1);free(saved_setting);}else unsetenv("COLOPHON_HOME");
}
TEST(runtime_home_matches_path_lexical_normalization) {
    const char *home=getenv("HOME"),*setting=getenv("COLOPHON_HOME");
    char *saved_home=home?strdup(home):NULL,*saved_setting=setting?strdup(setting):NULL;
    struct { const char *home,*input,*expected; } cases[]={
        {"/tmp/synthetic-home","./custom//","custom"},
        {"/tmp/synthetic-home","~/custom//","/tmp/synthetic-home/custom"},
        {"/tmp/synthetic-home","./~/custom//","/tmp/synthetic-home/custom"},
        {"/tmp/synthetic-home","~/.//../custom/.","/tmp/synthetic-home/../custom"},
        {"/tmp/synthetic-home","//custom///./more/..//","//custom/more/.."},
        {"/tmp/synthetic-home","///custom//","/custom"},
        {"//tmp//synthetic-home/.","~//custom//","//tmp/synthetic-home/custom"},
        {"relative/home//","~/custom//","relative/home/custom"},
        {"","~/custom//","/custom"},
        {"/tmp/synthetic-home","././/","."},
        {"/tmp/synthetic-home","//","//"},
        {"/tmp/synthetic-home","////","/"},
        {"/tmp/synthetic-home","a/./../b//","a/../b"}
    };
    for(size_t i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
        setenv("HOME",cases[i].home,1);setenv("COLOPHON_HOME",cases[i].input,1);
        char *path=NULL;ASSERT_EQ(ERR_OK,runtime_home(&path).code);
        ASSERT_STREQ(cases[i].expected,path);free(path);
    }
    if(saved_home){setenv("HOME",saved_home,1);free(saved_home);}else unsetenv("HOME");
    if(saved_setting){setenv("COLOPHON_HOME",saved_setting,1);free(saved_setting);}else unsetenv("COLOPHON_HOME");
}
TEST(runtime_home_honors_home_and_sweeps_only_old_regular_files) {
    char root[]="/tmp/colophon-home.XXXXXX"; ASSERT_TRUE(mkdtemp(root));
    const char *home=getenv("HOME"), *override=getenv("COLOPHON_HOME");
    char *saved_home=home?strdup(home):NULL, *saved_override=override?strdup(override):NULL;
    setenv("HOME",root,1); unsetenv("COLOPHON_HOME");
    char *resolved=NULL; ASSERT_EQ(ERR_OK,runtime_home(&resolved).code);
    char expected[512]; snprintf(expected,sizeof(expected),"%s/.colophon",root); ASSERT_STREQ(expected,resolved); free(resolved);
    setenv("COLOPHON_HOME","~/custom",1); ASSERT_EQ(ERR_OK,runtime_home(&resolved).code);
    snprintf(expected,sizeof(expected),"%s/custom",root); ASSERT_STREQ(expected,resolved); free(resolved);
    char old[512], recent[512], link[512], directory[512];
    snprintf(old,sizeof(old),"%s/.old.tmp",root); snprintf(recent,sizeof(recent),"%s/.recent.tmp",root);
    snprintf(link,sizeof(link),"%s/.link.tmp",root); snprintf(directory,sizeof(directory),"%s/.dir.tmp",root);
    int fd=open(old,O_CREAT|O_WRONLY,0600); ASSERT_TRUE(fd>=0); close(fd);
    fd=open(recent,O_CREAT|O_WRONLY,0600); ASSERT_TRUE(fd>=0); close(fd);
    struct timespec ts[2]={{0,0},{0,0}}; ASSERT_EQ(0,utimensat(AT_FDCWD,old,ts,0));
    ts[0].tv_sec=ts[1].tv_sec=3600; ASSERT_EQ(0,utimensat(AT_FDCWD,recent,ts,0));
    ASSERT_EQ(0,symlink(old,link)); ASSERT_EQ(0,mkdir(directory,0700));
    setenv("COLOPHON_TEST_WALL_MS","7200000",1);
    ASSERT_EQ(ERR_OK,ensure_runtime_home(root).code);
    struct stat st; ASSERT_EQ(-1,lstat(old,&st)); ASSERT_EQ(0,lstat(recent,&st));
    ASSERT_EQ(0,lstat(link,&st)); ASSERT_TRUE(S_ISLNK(st.st_mode)); ASSERT_EQ(0,lstat(directory,&st));
    ASSERT_EQ(0700,st.st_mode&0777); unsetenv("COLOPHON_TEST_WALL_MS");
    unlink(recent); unlink(link); rmdir(directory); rmdir(root);
    if(saved_home){setenv("HOME",saved_home,1);free(saved_home);}else unsetenv("HOME");
    if(saved_override){setenv("COLOPHON_HOME",saved_override,1);free(saved_override);}else unsetenv("COLOPHON_HOME");
}
