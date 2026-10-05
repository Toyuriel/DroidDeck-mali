/*
 * Steam updater rename compatibility for Android/PRoot.
 *
 * Android's app seccomp policy can answer ENOSYS for renameat2 before PRoot's own
 * seccomp trace action gets a chance to translate it. Steam's updater treats that
 * as an update failure and loops forever at "Installing update".
 *
 * Plain rename(2) semantics do not need renameat2. Force those calls through the
 * older renameat syscall, which Android allows and PRoot already translates.
 * Advanced renameat2 flags are left untouched unless flags == 0.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>

static void bl_log_rename_compat(const char *what) {
  static int logged;
  if (!logged) {
    logged = 1;
    dprintf(STDERR_FILENO, "DroidDeck: Steam rename compatibility active (%s)\n", what);
  }
}

int rename(const char *oldpath, const char *newpath) {
#ifdef SYS_renameat
  long rc = syscall(SYS_renameat, AT_FDCWD, oldpath, AT_FDCWD, newpath);
  if (rc < 0 && errno == ENOSYS) bl_log_rename_compat("renameat ENOSYS");
  return (int)rc;
#else
  errno = ENOSYS;
  return -1;
#endif
}

int renameat(int olddirfd, const char *oldpath, int newdirfd, const char *newpath) {
#ifdef SYS_renameat
  long rc = syscall(SYS_renameat, olddirfd, oldpath, newdirfd, newpath);
  if (rc < 0 && errno == ENOSYS) bl_log_rename_compat("renameat ENOSYS");
  return (int)rc;
#else
  errno = ENOSYS;
  return -1;
#endif
}

int renameat2(int olddirfd, const char *oldpath, int newdirfd, const char *newpath,
              unsigned int flags) {
  if (flags == 0)
    return renameat(olddirfd, oldpath, newdirfd, newpath);

#ifdef SYS_renameat2
  long rc = syscall(SYS_renameat2, olddirfd, oldpath, newdirfd, newpath, flags);
  if (rc < 0 && errno == ENOSYS)
    bl_log_rename_compat("renameat2 flags unsupported");
  return (int)rc;
#else
  errno = ENOSYS;
  bl_log_rename_compat("renameat2 syscall unavailable");
  return -1;
#endif
}
