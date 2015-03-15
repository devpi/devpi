function onIFrameLoad(iframe) {
    // place iframe's parent div below navigation
    var nav = $('div#navigation');
    $(iframe).parent().css('top', nav.offset().top + nav.outerHeight());
    // copy title
    var title = $(iframe.contentWindow.document).find('title').text();
    if (title) {
        $('title').text(title);
    }
}
