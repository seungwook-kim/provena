"""생성된 README 의 상대 링크 중 가리키는 파일이 없는 것을 글자만 남기고 링크를 푼다.
generate.sh 가 apiDocs·modelDocs=false 로 docs/*.md 를 만들지 않아(크기 절감) README 표의 링크가 404 가 되기 때문이다.
이미지 링크와 코드 블록(```) 안은 건드리지 않는다. 결과는 항상 LF 로 쓴다(git 이 LF 로 커밋).
사용: python strip_dead_links.py <README.md>...   (이미 푼 파일에 다시 돌려도 결과가 같다)"""
import pathlib
import re
import sys

LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")


def fix(path: pathlib.Path) -> int:
    count = 0

    def repl(m):
        nonlocal count
        target = m.group(2)
        if re.match(r"(https?:|mailto:|#)", target):
            return m.group(0)
        if (path.parent / re.split(r"[?#]", target)[0]).exists():
            return m.group(0)
        count += 1
        return m.group(1)

    out = []
    in_code = False
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
        else:
            out.append(line if in_code else LINK.sub(repl, line))
    if count:
        path.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return count


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(f"{name}: 깨진 링크 {fix(pathlib.Path(name))}개 풀었다")
