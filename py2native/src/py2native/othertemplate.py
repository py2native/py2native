configTemplate = r"""
        PyConfig_InitPythonConfig(&config);
        {
            wchar_t homebuf[4096];
            wchar_t fullbuf[4096];
            const wchar_t sep = L'/';
            if (argc && argv && argv[0]) {
                wcsncpy(homebuf, argv[0], (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                {
                    char narrow_path[4096];
                    char resolved_path[4096];
                    size_t converted = wcstombs(narrow_path, homebuf, sizeof(narrow_path) - 1);
                    if (converted != (size_t)-1) {
                        narrow_path[converted] = '\0';
                        if (realpath(narrow_path, resolved_path) != NULL) {
                            size_t wconverted = mbstowcs(fullbuf, resolved_path, (sizeof(fullbuf) / sizeof(fullbuf[0])) - 1);
                            if (wconverted != (size_t)-1) {
                                fullbuf[wconverted] = L'\0';
                                wcsncpy(homebuf, fullbuf, (sizeof(homebuf) / sizeof(homebuf[0])) - 1);
                                homebuf[(sizeof(homebuf) / sizeof(homebuf[0])) - 1] = L'\0';
                            }
                        }
                    }
                }
                wchar_t *last = wcsrchr(homebuf, sep);
                if (last) {
                    *last = L'\0';
                    wchar_t *last2 = wcsrchr(homebuf, sep);
                    if (last2 && wcscmp(last2 + 1, L"bin") == 0) {
                        *last2 = L'\0';
                    }
                    status = PyConfig_SetString(&config, &config.home, homebuf);
                    if (PyStatus_Exception(status)) {
                        PyConfig_Clear(&config);
                        return 1;
                    }
                }
            }
        }
"""
