import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', help='name of the image that has to be loaded')
    parser.add_argument('--name', help='name of the deployment ')
    args = parser.parse_args()

    print(args.images)
    print(args.name)


if __name__ == '__main__':
    main()


