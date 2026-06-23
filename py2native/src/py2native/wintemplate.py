configTemplate = r"""
        PyConfig_InitPythonConfig(&config);
        {
            wchar_t homebuf[4096];
            const wchar_t sep = L'\\';
            if (argc && argv && argv[0]) {
                wcsncpy(homebuf, argv[0], (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                wchar_t *last = wcsrchr(homebuf, sep);
                if (last) {
                    *last = L'\0';
                    wchar_t *last2 = wcsrchr(homebuf, sep);
                    if (last2 && _wcsicmp(last2 + 1, L"Scripts") == 0) {
                        wchar_t venvbuf[4096];
                        wchar_t cfgpath[4096];
                        FILE *cfg = NULL;
                        char line[4096];

                        wcsncpy(venvbuf, homebuf, (sizeof(venvbuf) / sizeof(venvbuf[0])) - 1);
                        venvbuf[(sizeof(venvbuf) / sizeof(venvbuf[0])) - 1] = L'\0';
                        *last2 = L'\0';
                        wcsncpy(cfgpath, homebuf, (sizeof(cfgpath) / sizeof(cfgpath[0])) - 1);
                        cfgpath[(sizeof(cfgpath) / sizeof(cfgpath[0])) - 1] = L'\0';
                        if ((wcslen(cfgpath) + 11) < (sizeof(cfgpath) / sizeof(cfgpath[0]))) {
                            wcscat(cfgpath, L"\\pyvenv.cfg");
                            cfg = _wfopen(cfgpath, L"rb");
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
