"""생성된 README 의 상대 링크 중 가리키는 파일이 없는 것을 글자만 남기고 링크를 푼다.
generate.sh 가 apiDocs·modelDocs=false 로 docs/*.md 를 만들지 않아(크기 절감) README 표의 링크가 404 가 되기 때문이다.
사용: python strip_dead_links.py <README.md>...   (이미 푼 파일에 다시 돌려도 결과가 같다)"""
import pathlib
import re
import sys

LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def fix(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8")
    count = 0

    def repl(m):
        nonlocal count
        target = m.group(2)
        if re.match(r"(https?:|mailto:|#)", target) or (path.parent / target.split("#")[0]).exists():
            return m.group(0)
        count += 1
        return m.group(1)

    new = LINK.sub(repl, text)
    if count:
        path.write_bytes(new.encode("utf-8")) if "\r\n" in text else path.write_text(new, encoding="utf-8", newline="\n")
    return count


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(f"{name}: 깨진 링크 {fix(pathlib.Path(name))}개 풀었다")
