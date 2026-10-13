#include "page.h"
#include "gen/assets.h"
#include <string.h>
Err page_render(const JsonWriter *payload,JsonWriter *page){
    if(payload->error.code!=ERR_OK)return payload->error;
    const char *s=(const char *)cp_asset_page_template;size_t n=cp_asset_page_template_len;
    const char *markers[]={"/*@@FONTS@@*/","/*@@CSS@@*/","/*@@JS@@*/","@@DATA@@"};
    const void *values[]={cp_asset_font_css,cp_asset_page_css,cp_asset_page_js,payload->data};
    size_t lengths[]={cp_asset_font_css_len,cp_asset_page_css_len,cp_asset_page_js_len,payload->length};
    for(size_t pos=0;pos<n;){size_t start=pos;int k=-1;
        while(pos<n){for(int j=0;j<4;j++){size_t m=strlen(markers[j]);if(m<=n-pos&&!memcmp(s+pos,markers[j],m)){k=j;break;}}if(k>=0)break;pos++;}
        jsonw_bytes(page,s+start,pos-start);if(k>=0){jsonw_bytes(page,values[k],lengths[k]);pos+=strlen(markers[k]);}}
    return page->error;
}
