import argparse
import pathlib

#from .l2test.l2test1 import l2test1Test

def main():
    parser = argparse.ArgumentParser(description="Py2Native Test",
                                     epilog="(C) Copyright 2026 by RSJ Software GmbH Germering. All rights reserved.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--license", type=pathlib.Path, help="License File")
    args = parser.parse_args()


    #print(py2native_runtime.__features__)

    if args.license:
        licenseString = args.license.read_text()
        license = _runtime_verify_es256_jwt(licenseString, None, None)
        print(license)

    #l2test1Test()

if __name__ == '__main__':
    main()

