#define _DARWIN_C_SOURCE
#include "browser.h"
#include "out/jsonw.h"
#include "testing/hooks.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
static bool executable(const char *name){
    if(strchr(name,'/'))return access(name,X_OK)==0;
    const char *path=getenv("PATH");if(!path)path="/usr/bin:/bin";
    const char *p=path;
    do{const char *end=strchr(p,':');size_t n=end?(size_t)(end-p):strlen(p);
        char *candidate=malloc(n+strlen(name)+2);if(!candidate)return false;
        if(n)snprintf(candidate,n+strlen(name)+2,"%.*s/%s",(int)n,p,name);
        else snprintf(candidate,n+strlen(name)+2,"%s",name);
        bool found=access(candidate,X_OK)==0;free(candidate);if(found)return true;
        if(!end)break;p=end+1;
    }while(true);return false;
}
static bool launch(char *const *argv,const char *script,bool quiet){
    int fds[2]={-1,-1};if(script&&pipe(fds))return false;
    pid_t pid=fork();if(pid<0){if(script){close(fds[0]);close(fds[1]);}return false;}
    if(!pid){if(script){close(fds[1]);dup2(fds[0],STDIN_FILENO);close(fds[0]);}
        if(quiet){int fd=open("/dev/null",O_RDWR);if(fd>=0){dup2(fd,STDIN_FILENO);dup2(fd,STDOUT_FILENO);dup2(fd,STDERR_FILENO);if(fd>2)close(fd);}setsid();}
        execvp(argv[0],argv);_exit(127);}
    if(script){close(fds[0]);struct sigaction old,ignore={0};ignore.sa_handler=SIG_IGN;sigaction(SIGPIPE,&ignore,&old);
        size_t used=0,n=strlen(script);while(used<n){ssize_t amount=write(fds[1],script+used,n-used);if(amount<0&&errno==EINTR)continue;if(amount<=0)break;used+=(size_t)amount;}
        close(fds[1]);sigaction(SIGPIPE,&old,NULL);}
    int status;
    if(quiet){struct timespec start,now;clock_gettime(CLOCK_MONOTONIC,&start);
        for(;;){pid_t found=waitpid(pid,&status,WNOHANG);if(found==pid)break;if(found<0&&errno!=EINTR)return false;
            clock_gettime(CLOCK_MONOTONIC,&now);double elapsed=(double)(now.tv_sec-start.tv_sec)+(double)(now.tv_nsec-start.tv_nsec)/1e9;
            if(elapsed>=5)return true;struct timespec pause={0,10000000};nanosleep(&pause,NULL);}}
    else while(waitpid(pid,&status,0)<0){if(errno!=EINTR)return false;}
    return WIFEXITED(status)&&WEXITSTATUS(status)==0;
}
static bool apple(const char *name,const char *url){
    /* Failure hook protects tests from every osascript launch, including named
     * registrations explicitly selected by BROWSER. */
    if(cp_browser_fallback_fail())return false;
    JsonWriter script={0};
    if(!strcmp(name,"default"))jsonw_raw(&script,
        "\n                        use framework \"AppKit\"\n                        use AppleScript version \"2.4\"\n                        use scripting additions\n\n"
        "                        property NSWorkspace : a reference to current application's NSWorkspace\n"
        "                        property NSURL : a reference to current application's NSURL\n\n"
        "                        set http_url to NSURL's URLWithString:\"https://python.org\"\n"
        "                        set browser_url to (NSWorkspace's sharedWorkspace)'s ¬\n"
        "                            URLForApplicationToOpenURL:http_url\n"
        "                        set app_path to browser_url's relativePath as text -- NSURL to absolute path '/Applications/Safari.app'\n\n"
        "                        tell application app_path\n                            activate\n                            open location \"");
    else{jsonw_raw(&script,"\n                   tell application \"");jsonw_raw(&script,name);jsonw_raw(&script,"\"\n                       activate\n                       open location \"");}
    jsonw_raw(&script,url);
    jsonw_raw(&script,!strcmp(name,"default")?"\"\n                        end tell\n                    ":"\"\n                   end\n                   ");
    char *argv[]={"/usr/bin/osascript",NULL};bool ok=script.error.code==ERR_OK&&launch(argv,script.data,false);jsonw_free(&script);return ok;
}
static bool elinks(const char *name,const char *url){
    JsonWriter arg={0};jsonw_raw(&arg,"openURL(");jsonw_raw(&arg,url);jsonw_raw(&arg,")");
    char *remote[]={(char *)name,"-remote",arg.data,NULL};bool ok=arg.error.code==ERR_OK&&launch(remote,NULL,true);jsonw_free(&arg);
    if(!ok){char *direct[]={(char *)name,(char *)url,NULL};ok=launch(direct,NULL,false);}return ok;
}
static bool background(char *const *argv){
    int fds[2];if(pipe(fds))return false;fcntl(fds[1],F_SETFD,FD_CLOEXEC);
    pid_t pid=fork();if(pid<0){close(fds[0]);close(fds[1]);return false;}
    if(!pid){close(fds[0]);setsid();execvp(argv[0],argv);int error=errno;(void)write(fds[1],&error,sizeof error);_exit(127);}
    close(fds[1]);int error=0;ssize_t n;do{n=read(fds[0],&error,sizeof error);}while(n<0&&errno==EINTR);close(fds[0]);
    int status;if(n!=0){while(waitpid(pid,&status,0)<0&&errno==EINTR){}return false;}
    /* Python's BackgroundBrowser succeeds only while poll() is None, even
     * when an already-finished process happened to exit zero. */
    return waitpid(pid,&status,WNOHANG)==0;
}
static void free_words(char **words,size_t n){for(size_t i=0;i<n;i++)free(words[i]);free(words);}
static bool command_template(const char *command,const char *url,bool *invalid){
    size_t count=0,capacity=8;char **words=calloc(capacity,sizeof *words);if(!words)return false;
    const char *p=command;bool valid=true;
    while(*p&&valid){while(*p&&strchr(" \t\r\n",*p))p++;if(!*p)break;JsonWriter token={0};char quote=0;bool started=false;
        while(*p){char c=*p++;if(!quote&&strchr(" \t\r\n",c))break;
            if(c=='\''&&quote!='"'){started=true;quote=quote?0:'\'';continue;}
            if(c=='"'&&quote!='\''){started=true;quote=quote?0:'"';continue;}
            if(c=='\\'&&quote!='\''){if(!*p){valid=false;break;}char next=*p++;
                if(quote=='"'&&next!='"'&&next!='\\')jsonw_bytes(&token,"\\",1);
                c=next;}
            started=true;jsonw_bytes(&token,&c,1);
        }
        if(quote||token.error.code!=ERR_OK)valid=false;
        if(valid&&started){JsonWriter expanded={0};const char *s=token.data?token.data:"";
            if(!count)jsonw_raw(&expanded,s); /* GenericBrowser keeps self.name literal. */
            else while(*s){const char *mark=strstr(s,"%s");if(!mark){jsonw_raw(&expanded,s);break;}jsonw_bytes(&expanded,s,(size_t)(mark-s));jsonw_raw(&expanded,url);s=mark+2;}
            if(!expanded.data)jsonw_raw(&expanded,"");if(expanded.error.code!=ERR_OK)valid=false;
            if(count+1==capacity){capacity*=2;char **grown=realloc(words,capacity*sizeof *words);if(!grown)valid=false;else words=grown;}
            if(valid){words[count++]=expanded.data;expanded.data=NULL;}jsonw_free(&expanded);
        }jsonw_free(&token);
    }
    bool bg=count&&!strcmp(words[count-1],"&");if(bg)free(words[--count]);
    if(count)words[count]=NULL;
    *invalid=!valid;bool ok=valid&&count&&(bg?background(words):launch(words,NULL,false));free_words(words,count);return ok;
}
static bool entry(const char *name,const char *url,bool *invalid){
    if(strstr(name,"%s"))return command_template(name,url,invalid);
    char *lower=strdup(name);if(!lower)return false;for(char *p=lower;*p;p++)*p=(char)tolower((unsigned char)*p);
    bool simple=!strpbrk(name," \t");const char *registered=NULL;
    if(simple){if(!strcmp(lower,"macosx"))registered="default";else if(!strcmp(lower,"chrome"))registered="google chrome";else if(!strcmp(lower,"firefox"))registered="firefox";else if(!strcmp(lower,"safari"))registered="safari";}
    bool ok=false;
    if(registered)ok=apple(registered,url);
    else{
        /* _synthesize compares the first word's basename with a registered
         * controller basename. Chrome's basename is 'google chrome'. */
        char *word=strdup(name);if(word){word[strcspn(word," \t\r\n")]=0;bool found=executable(word);char *base=strrchr(word,'/');base=base?base+1:word;
            for(char *p=base;*p;p++)*p=(char)tolower((unsigned char)*p);
            bool synth=found&&(!strcmp(base,"firefox")||!strcmp(base,"safari"));
            bool registered_elinks=simple&&!strcmp(lower,"elinks")&&executable("elinks");
            bool is_elinks=getenv("TERM")&&*getenv("TERM")&&executable("elinks")&&(registered_elinks||(found&&!strcmp(base,"elinks")));
            if(synth)ok=apple(name,url);else if(is_elinks)ok=elinks(registered_elinks?"elinks":name,url);else{char *argv[]={(char *)name,(char *)url,NULL};ok=launch(argv,NULL,false);}free(word);}
    }free(lower);return ok;
}
bool browser_open(const char *output){
    char *absolute=realpath(output,NULL);if(!absolute)return false;
    JsonWriter url={0};jsonw_raw(&url,"file://");
    static const char hex[]="0123456789ABCDEF";
    for(const unsigned char *p=(unsigned char *)absolute;*p;p++){unsigned char c=*p;
        if((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||strchr("/-._~",c))jsonw_bytes(&url,p,1);
        else{char b[]={'%',hex[c>>4],hex[c&15]};jsonw_bytes(&url,b,3);}}
    free(absolute);if(url.error.code!=ERR_OK){jsonw_free(&url);return false;}
    const char *setting=getenv("BROWSER");bool opened=false,invalid=false;
    if(setting){char *copy=strdup(setting);if(copy){char *p=copy;do{char *end=strchr(p,':');if(end)*end=0;if(*p&&entry(p,url.data,&invalid)){opened=true;break;}if(invalid||!end)break;p=end+1;}while(true);free(copy);}}
    if(!opened&&!invalid&&!cp_browser_fallback_fail()){
        const char *apps[]={"default","google chrome","firefox","safari"};for(int i=0;i<4&&!opened;i++)opened=apple(apps[i],url.data);
        const char *term=getenv("TERM");if(term&&*term){const char *names[]={"www-browser","links","elinks","lynx","w3m"};for(int i=0;i<5&&!opened;i++)if(executable(names[i])){if(i==2)opened=elinks(names[i],url.data);else{char *argv[]={(char *)names[i],url.data,NULL};opened=launch(argv,NULL,false);}}}
    }jsonw_free(&url);return opened;
}
