$(function() {
    $('.testresult').addClass('closed');
    $('.testresult_title').click(function () {
        $(this).parent().toggleClass('closed opened');
    });
});
