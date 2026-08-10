configTemplate = r"""
        PyConfig_InitPythonConfig(&config);
        {
            #include <unistd.h>
            wchar_t homebuf[4096];
            wchar_t fullbuf[4096];
            const wchar_t sep = L'/';
            if (argc && argv && argv[0]) {
                wcsncpy(homebuf, argv[0], (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                {
                    char narrow_path[4096];
                    char resolved_path[4096];
                    int resolved = 0;
                    size_t converted = wcstombs(narrow_path, homebuf, sizeof(narrow_path) - 1);
                    if (converted != (size_t)-1) {
                        narrow_path[converted] = '\0';
#ifdef __linux__
                        if (realpath("/proc/self/exe", resolved_path) != NULL) {
                            resolved = 1;
                        }
#endif
                        if (!resolved && strchr(narrow_path, '/') == NULL) {
                            char *env_path = getenv("PATH");
                            if (env_path) {
                                char path_copy[4096];
                                strncpy(path_copy, env_path, sizeof(path_copy) - 1);
                                path_copy[sizeof(path_copy) - 1] = '\0';
                                char *token = strtok(path_copy, ":");
                                while (token != NULL) {
                                    char candidate[4096];
                                    snprintf(candidate, sizeof(candidate), "%s/%s", token, narrow_path);
                                    if (access(candidate, X_OK) == 0) {
                                        if (realpath(candidate, resolved_path) != NULL) {
                                            resolved = 1;
                                            break;
                                        }
                                    }
                                    token = strtok(NULL, ":");
                                }
                            }
                        }
                        if (!resolved) {
                            if (realpath(narrow_path, resolved_path) != NULL) {
                                resolved = 1;
                            }
                        }
                        if (resolved) {
                            size_t wconverted = mbstowcs(fullbuf, resolved_path, (sizeof(fullbuf) / sizeof(fullbuf[0])) - 1);
                            if (wconverted != (size_t)-1) {
                                fullbuf[wconverted] = L'\0';
                                wcsncpy(homebuf, fullbuf, (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                                homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                            }
                        }
                    }
                }
                status = PyConfig_SetString(&config, &config.executable, homebuf);
                if (PyStatus_Exception(status)) {
                    PyConfig_Clear(&config);
                    return 1;
                }
                wchar_t *last = wcsrchr(homebuf, sep);
                if (last) {
                    *last = L'\0';
                    wchar_t *last2 = wcsrchr(homebuf, sep);
                    if (last2 && wcscmp(last2 + 1, L"bin") == 0) {
                        wchar_t venvbuf[4096];
                        wchar_t cfgpath[4096];
                        char narrow_cfg[4096];
                        FILE *cfg = NULL;
                        char line[4096];

                        wcsncpy(venvbuf, homebuf, (sizeof(venvbuf) / sizeof(venvbuf[0])) - 1);
                        venvbuf[(sizeof(venvbuf) / sizeof(venvbuf[0])) - 1] = L'\0';
                        *last2 = L'\0';
                        wcsncpy(cfgpath, homebuf, (sizeof(cfgpath) / sizeof(cfgpath[0])) - 1);
                        cfgpath[(sizeof(cfgpath) / sizeof(cfgpath[0])) - 1] = L'\0';
                        if ((wcslen(cfgpath) + 12) < (sizeof(cfgpath) / sizeof(cfgpath[0]))) {
                            wcscat(cfgpath, L"/pyvenv.cfg");
                            size_t converted_cfg = wcstombs(narrow_cfg, cfgpath, sizeof(narrow_cfg) - 1);
                            if (converted_cfg != (size_t)-1) {
                                narrow_cfg[converted_cfg] = '\0';
                                cfg = fopen(narrow_cfg, "r");
                                if (cfg != NULL) {
                                    while (fgets(line, sizeof(line), cfg)) {
                                        if (strncmp(line, "home", 4) == 0) {
                                            char *eq = strchr(line, '=');
                                            if (eq != NULL) {
                                                char *value = eq + 1;
                                                while (*value == ' ' || *value == '\t') {
                                                    value++;
                                                }
                                                char *end = value + strlen(value);
                                                while (end > value && (end[-1] == '\n' || end[-1] == '\r' || end[-1] == ' ' || end[-1] == '\t')) {
                                                    end--;
                                                }
                                                *end = '\0';
                                                if (*value) {
                                                    wchar_t home_from_cfg[4096];
                                                    size_t converted = mbstowcs(home_from_cfg, value, (sizeof(home_from_cfg) / sizeof(home_from_cfg[0])) - 1);
                                                    if (converted != (size_t)-1) {
                                                        home_from_cfg[converted] = L'\0';
                                                        status = PyConfig_SetString(&config, &config.home, home_from_cfg);
                                                        if (PyStatus_Exception(status)) {
                                                            PyConfig_Clear(&config);
                                                            fclose(cfg);
                                                            return 1;
                                                        }
                                                    }
                                                }
                                            }
                                            break;
                                        }
                                    }
                                    fclose(cfg);
                                }
                            }
                        }
                        wcsncpy(homebuf, venvbuf, (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                        homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                    } else {
                        /* Not a venv: set home to the directory containing this executable */
                        status = PyConfig_SetString(&config, &config.home, homebuf);
                        if (PyStatus_Exception(status)) {
                            PyConfig_Clear(&config);
                            return 1;
                        }
                    }
                }
            }
        }
"""
