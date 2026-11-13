"""Builds small real PDFs in memory for the PDF text tests."""

import io

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject


def _image_xobject(writer: PdfWriter):
    image = StreamObject()
    image[NameObject("/Type")] = NameObject("/XObject")
    image[NameObject("/Subtype")] = NameObject("/Image")
    image[NameObject("/Width")] = NumberObject(1)
    image[NameObject("/Height")] = NumberObject(1)
    image[NameObject("/ColorSpace")] = NameObject("/DeviceGray")
    image[NameObject("/BitsPerComponent")] = NumberObject(8)
    image.set_data(b"\x00")
    return writer._add_object(image)


def _form_wrapping_image(writer: PdfWriter):
    form = StreamObject()
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Im0"): _image_xobject(writer)}
            )
        }
    )
    form.set_data(b"/Im0 Do")
    return writer._add_object(form)


def pdf_bytes(
    page_texts: list[str],
    user_password: str | None = None,
    owner_password: str | None = None,
    image_pages: set[int] | None = None,
    form_image_pages: set[int] | None = None,
) -> bytes:
    """Build a PDF where each entry in page_texts becomes one page.

    An empty-string entry produces a page with no text content (the scanned-
    image shape). 1-indexed page numbers in image_pages get an image XObject in
    their resources; those in form_image_pages get the image nested inside a
    Form XObject. pypdf has no drawing API, so the content stream is assembled
    by hand from a Helvetica show-text operator.
    """
    writer = PdfWriter()
    for index, text in enumerate(page_texts, start=1):
        page = writer.add_blank_page(width=300, height=300)
        resources = DictionaryObject()
        if text:
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
            stream = StreamObject()
            stream.set_data(f"BT /F1 12 Tf 40 150 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
        if image_pages and index in image_pages:
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im0"): _image_xobject(writer)}
            )
        elif form_image_pages and index in form_image_pages:
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Fm0"): _form_wrapping_image(writer)}
            )
        if resources:
            page[NameObject("/Resources")] = resources
    if user_password is not None or owner_password is not None:
        writer.encrypt(
            user_password=user_password or "",
            owner_password=owner_password,
            algorithm="RC4-128",
        )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
