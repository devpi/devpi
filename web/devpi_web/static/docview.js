function updateIFrame(iframe) {
    // place iframe's parent div below navigation
    var $nav = $('div#navigation');
    $(iframe).parent().css('top', $nav.offset().top + $nav.outerHeight(true));
}

function onIFrameLoad(iframe) {
    updateIFrame(iframe);
    $(window).resize(function () {
        updateIFrame(iframe);
    });
    // copy title
    var title = $(iframe.contentWindow.document).find('title').text();
    if (title) {
        $('title').text(title);
    }
}
