# Glossary Map

## Contexts

- [Resume Scanning](./GLOSSARY.md): HR requirement intake, resume extraction and candidate evaluation
- [Nữ Giới Chung](./src/nugioichung/GLOSSARY.md): transcribing scanned issues of the 1918 newspaper _Nữ Giới Chung_ into text
- [Kho tàng tục ngữ người Việt](./vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md): transcribing the scanned two-volume proverb collection into text

## Relationships

- **Nữ Giới Chung ↔ Resume Scanning**: none in the domain. Nữ Giới Chung only shares the infrastructure that serves and calls the model.
- **Kho tàng tục ngữ người Việt ↔ Nữ Giới Chung, Resume Scanning**: none in the domain. Its pipeline (`src/khotangtucngu`) only shares the infrastructure that serves and calls the model.
