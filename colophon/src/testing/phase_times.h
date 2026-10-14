#ifndef CP_PHASE_TIMES_H
#define CP_PHASE_TIMES_H
#ifdef COLOPHON_TESTING
#include <stdbool.h>
void cp_phase_start(bool enabled);
void cp_phase_mark(unsigned stage);
void cp_phase_finish(void);
#define CP_PHASE_START(enabled) cp_phase_start(enabled)
#define CP_PHASE_MARK(stage) cp_phase_mark(stage)
#define CP_PHASE_FINISH() cp_phase_finish()
#else
#define CP_PHASE_START(enabled) ((void)0)
#define CP_PHASE_MARK(stage) ((void)0)
#define CP_PHASE_FINISH() ((void)0)
#endif
#endif
