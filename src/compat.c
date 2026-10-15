#include <sys/types.h>
#include <sys/sysctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdint.h>
#include <dirent.h>

int xpp_mac_directory_access(const char *path) {
    if (faccessat(AT_FDCWD, path, R_OK | X_OK, AT_EACCESS) != 0) return errno;
    DIR *d = opendir(path);
    if (!d) return errno;
    if (closedir(d) != 0) return errno;
    return 0;
}
uint64_t xpp_mac_physical_memory(void) {
    uint64_t size = 0;
    size_t len = sizeof(size);
    return sysctlbyname("hw.memsize", &size, &len, NULL, 0) == 0 ? size : 0;
}
