#define _DARWIN_C_SOURCE
#include "time.h"
#include <time.h>
#include <stdio.h>
#include "events.h"
#include "pynum.h"
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <time.h>

static bool range_failure(const char *site) {
    event_note("tier2_time", site, 1);
    return false;
}
bool time_ms_from_i64(int64_t v, bool milliseconds, const char *site, int64_t *ms) {
    return time_ms_from_i64_once(v, milliseconds, site, NULL, ms);
}
bool time_ms_from_i64_once(int64_t v, bool milliseconds, const char *site,
                           bool *range_noted, int64_t *ms) {
    if (!milliseconds && (v > INT64_MAX / 1000 || v < INT64_MIN / 1000)) {
        if (!range_noted || !*range_noted) {
            range_failure(site);
            if (range_noted)
                *range_noted = true;
        }
        return false;
    }
    *ms = milliseconds ? v : v * 1000;
    return true;
}
static bool double_ms(double v, const char *site, int64_t *ms) {
    if (!isfinite(v)) return false;
    if (v >= 0x1p63 || v < -0x1p63) return range_failure(site);
    *ms = (int64_t)v;
    return true;
}
bool time_truncate_ms(double scaled_ms, const char *site, int64_t *ms) {
    return double_ms(scaled_ms, site, ms);
}
bool time_round_swift_ms(double seconds, const char *site, int64_t *ms) {
    if (!isfinite(seconds)) return false;
    double v = seconds * 1000;
    if (!isfinite(v)) return range_failure(site);
    return double_ms(v >= 0 ? floor(v + 0.5) : ceil(v - 0.5), site, ms);
}
static int number(Str s, size_t i, size_t n) {
    if (i > s.n || n > s.n - i) return -1;
    int v = 0;
    for (size_t j = 0; j < n; j++) {
        unsigned char c = (unsigned char)s.p[i+j];
        if (c < '0' || c > '9') return -1;
        v = v * 10 + c - '0';
    }
    return v;
}
/* Proleptic Gregorian civil date; month is normalized by the caller. */
static int64_t civil_days(int y, int m, int d) {
    y -= m <= 2;
    int era = (y >= 0 ? y : y - 399) / 400;
    unsigned yo = (unsigned)(y - era * 400);
    unsigned doy = (153 * (unsigned)(m + (m > 2 ? -3 : 9)) + 2) / 5;
    unsigned doe = yo * 365 + yo / 4 - yo / 100 + doy;
    return (int64_t)era * 146097 + doe + d - 1 - 719468;
}
static bool calendar(int y, int m, int d) {
    static const int days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
    if (y < 1 || m < 1 || m > 12 || d < 1) return false;
    int limit = days[m-1] + (m == 2 && y % 4 == 0 && (y % 100 != 0 || y % 400 == 0));
    return d <= limit;
}
bool time_parse_rfc3339_status(Str s, const char *site, int64_t *ms, bool *past_year_limit) {
    if(past_year_limit)*past_year_limit=false;
    if (s.n < 20 || s.p[4]!='-' || s.p[7]!='-' || (s.p[10]!='T' && s.p[10]!='t') || s.p[13]!=':' || s.p[16]!=':') return false;
    int y=number(s,0,4), m=number(s,5,2), d=number(s,8,2);
    int h=number(s,11,2), mi=number(s,14,2), sec=number(s,17,2);
    if (!calendar(y,m,d) || h<0 || h>24 || mi<0 || mi>59 || sec<0 || sec>59) return false;
    size_t i=19; int fraction=0, microseconds=0;
    if (s.p[i]=='.') {
        size_t start=++i;
        while (i<s.n && s.p[i]>='0' && s.p[i]<='9') {
            if (i-start<3) fraction=fraction*10+s.p[i]-'0';
            if (i-start<6) microseconds=microseconds*10+s.p[i]-'0';
            i++;
        }
        if (i==start) return false;
        for (size_t n=i-start; n<3; n++) fraction*=10;
    }
    if (h==24 && (mi || sec || microseconds)) return false;
    int offset=0;
    if (i<s.n && (s.p[i]=='Z' || s.p[i]=='z')) i++;
    else if (i<s.n && (s.p[i]=='+' || s.p[i]=='-')) {
        int sign=s.p[i]=='-'?-1:1;
        if (s.n-i!=6 || s.p[i+3]!=':') return false;
        int oh=number(s,i+1,2), om=number(s,i+4,2);
        if (oh<0 || oh>23 || om<0 || om>59) return false;
        offset=sign*(oh*3600+om*60); i+=6;
    } else return false;
    if (i!=s.n) return false;
    if (h==24 && y==9999 && m==12 && d==31) {if(past_year_limit)*past_year_limit=true;return range_failure(site);}
    int64_t seconds=civil_days(y,m,d)*86400+h*3600+mi*60+sec-offset;
    if (seconds<civil_days(1,1,1)*86400) return false;
    if (seconds>=civil_days(10000,1,1)*86400) {if(past_year_limit)*past_year_limit=true;return range_failure(site);}
    *ms=seconds*1000+fraction;
    return true;
}
bool time_parse_rfc3339(Str s,const char *site,int64_t *ms) {
    return time_parse_rfc3339_status(s,site,ms,NULL);
}
static bool local_day(int64_t ms, const char *site, char day[11]) {
    int64_t seconds; (void)floordiv_i64(ms,1000,&seconds);
    time_t t=(time_t)seconds;
    if ((int64_t)t!=seconds) return range_failure(site);
    struct tm local;
    if (!localtime_r(&t,&local)) return range_failure(site);
    int64_t y=(int64_t)local.tm_year+1900;
    if (y>9999) return range_failure(site);
    if (y<1) return false;
    snprintf(day,11,"%04d-%02d-%02d",(int)y,local.tm_mon+1,local.tm_mday);
    return true;
}
bool time_day_key(Str s, const char *site, char day[11], int64_t *ms) {
    if (s.n<20 || s.p[4]!='-' || s.p[7]!='-') return false;
    int y=number(s,0,4), m=number(s,5,2), d=number(s,8,2), h=0,mi=0,sec=0;
    if (y<0 || m<0 || d<0) return false;
    if (s.p[10]=='T') {
        if (s.p[13]!=':' || s.p[16]!=':') return false;
        h=number(s,11,2); mi=number(s,14,2); sec=number(s,17,2);
        if (h<0 || mi<0 || sec<0) return false;
    }
    size_t zone=s.n;
    for (size_t i=s.n; i>11;) {
        char c=s.p[--i];
        if (c=='Z' || c=='+' || c=='-') { zone=i; break; }
    }
    if (zone==s.n) return false;
    int offset=0;
    if (s.p[zone]!='Z') {
        size_t start=zone+1; int oh=number(s,start,2), om=0;
        if (oh<0) return false;
        if (s.n>start+2) {
            if (s.p[start+2]==':') { om=number(s,start+3,2); if (om<0) return false; }
            else if (number(s,start+2,2)>=0) om=number(s,start+2,2);
        }
        offset=(oh*3600+om*60)*(s.p[zone]=='-'?-1:1);
        if (offset>18*3600 || offset< -18*3600) return false;
    }
    int total=y*12+m-1;
    y=total/12-(total%12<0); m=total-y*12+1;
    int64_t seconds=civil_days(y,m,d)*86400+h*3600+mi*60+sec-offset;
    if (seconds>=civil_days(10000,1,1)*86400) return range_failure(site);
    int64_t result;
    if (!time_ms_from_i64(seconds,false,site,&result) || !local_day(result,site,day)) return false;
    *ms=result; return true;
}
bool time_codex_timestamp(Str s,const char *site,int64_t *ms) {
    if (s.n<20 || s.p[10]!='T' || number(s,0,4)<1900) return false;
    size_t i=19;
    if (s.p[i]=='.') {
        size_t start=++i;
        while (i<s.n && s.p[i]>='0' && s.p[i]<='9') i++;
        if (i-start<1 || i-start>9) return false;
    }
    if (i>=s.n || (s.p[i]!='Z' && s.p[i]!='+' && s.p[i]!='-')) return false;
    int64_t result;
    if (!time_parse_rfc3339(s,site,&result)) return false;
    *ms=result; return true;
}
bool time_day_key_iso(Str s,const char *site,char day[11],int64_t *ms) {
    int64_t result;
    if(!time_codex_timestamp(s,site,&result) || !local_day(result,site,day))return false;
    *ms=result;return true;
}
bool time_format_rfc3339(int64_t milliseconds,char output[21]) {
    int64_t seconds=milliseconds/1000;
    if(milliseconds%1000<0)seconds--;
    time_t value=(time_t)seconds;struct tm broken;
    if((int64_t)value!=seconds||!gmtime_r(&value,&broken)||broken.tm_year < -1899 || broken.tm_year>8099)return false;
    return snprintf(output,21,"%04d-%02d-%02dT%02d:%02d:%02dZ",broken.tm_year+1900,broken.tm_mon+1,broken.tm_mday,broken.tm_hour,broken.tm_min,broken.tm_sec)==20;
}
