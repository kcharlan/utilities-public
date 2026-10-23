#include "compose.h"
Err antigravity_compose(AntigravityStore *store,Corpus *corpus,ModelsDevIndex *index,PricingReport *report) {
    (void)store;(void)index;(void)report;
    for(OmapEntry *q=corpus->sessions.first;q;q=q->next) {
        SessionModel *s=q->value;if(s->provider!=PROVIDER_ANTIGRAVITY)continue;
        Err e=compose_aggregate_session(corpus,s);if(e.code)return e;
    }
    return ERR_SUCCESS;
}
