/* Scoped launcher for the local HOI4 globe rendering prototype.
   Loads the bridge only into the freshly created, hash-verified game process. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static const char expected_sha256[] =
    "7dc947be34970da1e1c787bcddbe7f62b610ff258aebf8f06aa8b348f3a031d5";

static const wchar_t *basename_of(const wchar_t *path) {
    const wchar_t *base = path;
    for (const wchar_t *p = path; *p; ++p)
        if (*p == L'\\' || *p == L'/') base = p + 1;
    return base;
}

static int absolute_path(const wchar_t *input, wchar_t output[MAX_PATH]) {
    DWORD length = GetFullPathNameW(input, MAX_PATH, output, NULL);
    if (!length || length >= MAX_PATH) return 0;
    for (wchar_t *p = output; *p; ++p) if (*p == L'/') *p = L'\\';
    return 1;
}

static int valid_pe(HANDLE file, int require_dll) {
    unsigned char header[64];
    DWORD read = 0;
    LARGE_INTEGER zero = {0};
    if (!SetFilePointerEx(file, zero, NULL, FILE_BEGIN) ||
        !ReadFile(file, header, sizeof(header), &read, NULL) || read != sizeof(header) ||
        header[0] != 'M' || header[1] != 'Z') return 0;
    uint32_t offset;
    memcpy(&offset, header + 0x3c, sizeof(offset));
    if (offset < sizeof(header) || offset > 0x100000) return 0;
    LARGE_INTEGER at; at.QuadPart = offset;
    unsigned char pe[26];
    if (!SetFilePointerEx(file, at, NULL, FILE_BEGIN) ||
        !ReadFile(file, pe, sizeof(pe), &read, NULL) || read != sizeof(pe)) return 0;
    uint16_t machine, flags, magic;
    memcpy(&machine, pe + 4, 2);
    memcpy(&flags, pe + 22, 2);
    memcpy(&magic, pe + 24, 2);
    return memcmp(pe, "PE\0\0", 4) == 0 && machine == IMAGE_FILE_MACHINE_AMD64 &&
        magic == 0x20b && !!(flags & IMAGE_FILE_DLL) == require_dll;
}

static int sha256_file(HANDLE file, char hex[65]) {
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    unsigned char *object = NULL;
    DWORD object_bytes = 0, returned = 0, count = 0;
    unsigned char digest[32], chunk[65536];
    LARGE_INTEGER zero = {0}, size;
    int ok = 0;
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 0 ||
        size.QuadPart > 256LL * 1024 * 1024 ||
        !SetFilePointerEx(file, zero, NULL, FILE_BEGIN)) goto done;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0 ||
        BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, (PUCHAR)&object_bytes,
            sizeof(object_bytes), &returned, 0) < 0 || !object_bytes) goto done;
    object = (unsigned char *)malloc(object_bytes);
    if (!object || BCryptCreateHash(algorithm, &hash, object, object_bytes, NULL, 0, 0) < 0)
        goto done;
    for (;;) {
        if (!ReadFile(file, chunk, sizeof(chunk), &count, NULL)) goto done;
        if (!count) break;
        if (BCryptHashData(hash, chunk, count, 0) < 0) goto done;
    }
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0) goto done;
    for (unsigned i = 0; i < sizeof(digest); ++i) sprintf(hex + 2 * i, "%02x", digest[i]);
    hex[64] = 0;
    ok = 1;
done:
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    free(object);
    return ok;
}

static int another_game_exists(void) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) return -1;
    PROCESSENTRY32W entry = {0}; entry.dwSize = sizeof(entry);
    int found = 0;
    if (!Process32FirstW(snapshot, &entry)) { CloseHandle(snapshot); return -1; }
    do {
        if (!_wcsicmp(entry.szExeFile, L"hoi4.exe")) { found = 1; break; }
    } while (Process32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    return found;
}

/* GetProcAddress can return KernelBase's forwarded implementation. Find its
   actual local owner and apply that RVA to the matching remote module. */
static uintptr_t remote_load_library(DWORD pid, HANDLE process) {
    HMODULE kernel = GetModuleHandleW(L"kernel32.dll"), owner = NULL;
    FARPROC load = kernel ? GetProcAddress(kernel, "LoadLibraryW") : NULL;
    wchar_t owner_path[MAX_PATH];
    if (!load || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCWSTR)(uintptr_t)load, &owner) ||
        !GetModuleFileNameW(owner, owner_path, MAX_PATH)) return 0;
    uintptr_t rva = (uintptr_t)load - (uintptr_t)owner;
    for (unsigned attempt = 0; attempt < 50; ++attempt) {
        if (WaitForSingleObject(process, 0) != WAIT_TIMEOUT) return 0;
        HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
        if (snapshot != INVALID_HANDLE_VALUE) {
            MODULEENTRY32W entry = {0}; entry.dwSize = sizeof(entry);
            if (Module32FirstW(snapshot, &entry)) do {
                if (!_wcsicmp(entry.szModule, basename_of(owner_path))) {
                    uintptr_t result = rva < entry.modBaseSize ?
                        (uintptr_t)entry.modBaseAddr + rva : 0;
                    CloseHandle(snapshot);
                    return result;
                }
            } while (Module32NextW(snapshot, &entry));
            CloseHandle(snapshot);
        }
        Sleep(100);
    }
    return 0;
}

static int loaded_module(DWORD pid, const wchar_t *path) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snapshot == INVALID_HANDLE_VALUE) return 0;
    MODULEENTRY32W entry = {0}; entry.dwSize = sizeof(entry);
    int found = 0;
    if (Module32FirstW(snapshot, &entry)) do {
        wchar_t full[MAX_PATH];
        if (absolute_path(entry.szExePath, full) && !_wcsicmp(full, path)) { found = 1; break; }
    } while (Module32NextW(snapshot, &entry));
    CloseHandle(snapshot);
    return found;
}

static int load_bridge(PROCESS_INFORMATION *pi, const wchar_t *dll) {
    uintptr_t load = remote_load_library(pi->dwProcessId, pi->hProcess);
    if (!load) { fprintf(stderr, "LAUNCH_ERROR=remote_load_library_unavailable\n"); return 0; }
    SIZE_T bytes = (wcslen(dll) + 1) * sizeof(wchar_t), written = 0;
    LPVOID argument = VirtualAllocEx(pi->hProcess, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!argument) { fprintf(stderr, "LAUNCH_ERROR=remote_argument_allocation\n"); return 0; }
    HANDLE thread = NULL;
    int ok = 0;
    if (!WriteProcessMemory(pi->hProcess, argument, dll, bytes, &written) || written != bytes) {
        fprintf(stderr, "LAUNCH_ERROR=remote_argument_write\n"); goto done;
    }
    thread = CreateRemoteThread(pi->hProcess, NULL, 0,
        (LPTHREAD_START_ROUTINE)load, argument, 0, NULL);
    if (!thread) { fprintf(stderr, "LAUNCH_ERROR=bridge_loading_thread\n"); goto done; }
    DWORD wait = WaitForSingleObject(thread, 15000);
    if (wait != WAIT_OBJECT_0) {
        fprintf(stderr, "LAUNCH_ERROR=bridge_loading_timeout\n");
        /* The caller terminates only its newly created process. Do not free the
           remote string while a live LoadLibraryW thread may still read it. */
        CloseHandle(thread);
        return 0;
    }
    for (unsigned attempt = 0; attempt < 20; ++attempt) {
        if (WaitForSingleObject(pi->hProcess, 0) != WAIT_TIMEOUT) break;
        if (loaded_module(pi->dwProcessId, dll)) { ok = 1; break; }
        Sleep(100);
    }
    if (!ok) fprintf(stderr, "LAUNCH_ERROR=bridge_module_not_loaded\n");
done:
    if (thread) CloseHandle(thread);
    VirtualFreeEx(pi->hProcess, argument, 0, MEM_RELEASE);
    return ok;
}

int wmain(int argc, wchar_t **argv) {
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    if (argc != 4 || (_wcsicmp(argv[3], L"play") && _wcsicmp(argv[3], L"test"))) {
        fprintf(stderr, "Usage: globe_launcher.exe <isolated-hoi4.exe> <hoi4_globe_native.dll> play|test\n");
        return 2;
    }
    int test = !_wcsicmp(argv[3], L"test");
    wchar_t exe[MAX_PATH], dll[MAX_PATH], directory[MAX_PATH], command[MAX_PATH + 80];
    if (!absolute_path(argv[1], exe) || !absolute_path(argv[2], dll) ||
        _wcsicmp(basename_of(exe), L"hoi4.exe") ||
        _wcsicmp(basename_of(dll), L"hoi4_globe_native.dll")) {
        fprintf(stderr, "LAUNCH_ERROR=invalid_game_or_bridge_path\n"); return 3;
    }
    /* Keep these handles open until loading finishes: the checked bytes cannot
       be changed or renamed between validation and execution. */
    HANDLE game_file = CreateFileW(exe, GENERIC_READ, FILE_SHARE_READ, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    HANDLE dll_file = CreateFileW(dll, GENERIC_READ, FILE_SHARE_READ, NULL,
        OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (game_file == INVALID_HANDLE_VALUE || dll_file == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "LAUNCH_ERROR=game_or_bridge_file_missing_or_locked\n");
        if (game_file != INVALID_HANDLE_VALUE) CloseHandle(game_file);
        if (dll_file != INVALID_HANDLE_VALUE) CloseHandle(dll_file);
        return 4;
    }
    char digest[65] = {0};
    int result = 5;
    if (!sha256_file(game_file, digest) || strcmp(digest, expected_sha256)) {
        fprintf(stderr, "LAUNCH_ERROR=unsupported_executable_hash\n");
        if (digest[0]) fprintf(stderr, "ACTUAL_SHA256=%s\n", digest);
        goto done;
    }
    if (!valid_pe(game_file, 0) || !valid_pe(dll_file, 1)) {
        fprintf(stderr, "LAUNCH_ERROR=invalid_64bit_game_or_dll\n"); result = 6; goto done;
    }
    if (!test) {
        int existing = another_game_exists();
        if (existing != 0) {
            fprintf(stderr, "LAUNCH_ERROR=%s\n", existing > 0 ? "game_already_running" : "process_inventory_failed");
            result = 7; goto done;
        }
    }
    wcscpy(directory, exe);
    wchar_t *slash = wcsrchr(directory, L'\\');
    if (!slash) { result = 3; goto done; }
    *slash = 0;
    if (swprintf(command, MAX_PATH + 80, L"\"%ls\" -gdpr-compliant%ls", exe,
        test ? L" -debug" : L"") < 0) { result = 3; goto done; }
    STARTUPINFOW startup = {0}; startup.cb = sizeof(startup);
    if (test) { startup.dwFlags = STARTF_USESHOWWINDOW; startup.wShowWindow = SW_HIDE; }
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(exe, command, NULL, NULL, FALSE,
        CREATE_UNICODE_ENVIRONMENT | (test ? CREATE_NO_WINDOW : 0), NULL,
        directory, &startup, &process)) {
        fprintf(stderr, "LAUNCH_ERROR=create_game_process WIN32_ERROR=%lu\n", GetLastError());
        result = 8; goto done;
    }
    CloseHandle(process.hThread);
    if (!load_bridge(&process, dll)) {
        TerminateProcess(process.hProcess, 9);
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hProcess);
        result = 9; goto done;
    }
    if (WaitForSingleObject(process.hProcess, 0) != WAIT_TIMEOUT) {
        fprintf(stderr, "LAUNCH_ERROR=game_exited_during_bridge_loading\n");
        CloseHandle(process.hProcess); result = 10; goto done;
    }
    printf("LAUNCHED_PID=%lu\nBRIDGE_MODULE_LOADED=true\n", process.dwProcessId);
    fflush(stdout);
    CloseHandle(process.hProcess);
    result = 0;
done:
    CloseHandle(game_file);
    CloseHandle(dll_file);
    return result;
}
