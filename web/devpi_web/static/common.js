function get_anchor(document, hash) {
    hash = decodeURIComponent(hash.replace('#', ''));
    if (!hash) {
        return;
    }
    var anchor = document.getElementById(hash);
    if (!anchor) {
        var selector = 'a[name="' + hash + '"]';
        anchor = $(document).find(selector);
        if (!anchor.length) {
            return;
        }
        return anchor[0];
    }
    return anchor;
}

$(function() {
    var anchor = get_anchor(document, window.location.hash);
    if (anchor !== null) {
        anchor = $(anchor).parent('.toxresult');
        if (anchor.length) {
            anchor = anchor[0]
        } else {
            anchor = null;
        }
    }
    $('.toxresult.passed').each(function() {
        if (this === anchor) {
            $(this).addClass('opened');
        } else {
            $(this).addClass('closed');
        }
    });
    $('.toxresult.failed').addClass('opened');
    $('table.projectinfos .is_list').addClass('closed');
    $('.toxresult h2, table.projectinfos .is_list .value').click(function () {
        $(this).parent().toggleClass('closed opened');
    });
    $('.timestamp').each(function() {
        var element = $(this);
        var time = new Date(element.text());
        if (isNaN(time)) {
            return;
        }
        time = new Date(Date.UTC(
            time.getFullYear(), time.getMonth(), time.getDate(),
            time.getHours(), time.getMinutes(), time.getSeconds()));
        var iso = time.toISOString();
        element.text(iso.slice(0, 10));
        element.attr("title", iso);
    });
});
