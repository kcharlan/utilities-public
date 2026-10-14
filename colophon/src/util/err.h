#ifndef CP_ERR_H
#define CP_ERR_H
typedef enum { ERR_OK, ERR_NOMEM, ERR_INVALID, ERR_IO } ErrCode;
typedef struct {
    ErrCode code;
    char message[256];
} Err;
Err err_make(ErrCode code, const char *format, ...);
/* Copies errno text into caller-owned storage; safe on scan workers. */
const char *err_system(int number, char buffer[256]);
#define ERR_SUCCESS ((Err){ERR_OK, {0}})
#endif
